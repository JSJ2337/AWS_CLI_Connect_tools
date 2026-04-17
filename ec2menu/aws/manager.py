"""AWS 리소스 관리 (EC2/SSM/RDS/ElastiCache/ECS/EKS/CloudWatch/Lambda/S3)"""
from __future__ import annotations

import base64
import concurrent.futures
import json
import logging
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound

from ec2menu.core.cache import _cache
from ec2menu.core.colors import Colors, colored_text
from ec2menu.core.config import Config


class AWSManager:
    def __init__(self, profile: str, max_workers: int = Config.DEFAULT_WORKERS):
        try:
            self.session = boto3.Session(profile_name=profile)
        except ProfileNotFound as e:
            print(colored_text(f"❌ AWS 프로파일 오류: {e}", Colors.ERROR))
            sys.exit(1)
        self.profile = profile
        self.max_workers = max_workers

    # -------------------------------------------------------------------------
    # EC2 / SSM
    # -------------------------------------------------------------------------

    def list_regions(self) -> List[str]:
        cache_key = f"regions_{self.profile}"
        cached_data = _cache.get(cache_key)
        if cached_data:
            return cached_data

        try:
            default_region = self.session.region_name or 'us-east-1'
            ec2 = self.session.client('ec2', region_name=default_region)
            resp = ec2.describe_regions(AllRegions=False)
            regions = [r['RegionName'] for r in resp.get('Regions', [])]
            _cache.set(cache_key, regions, ttl_seconds=3600)
            return regions
        except (ClientError, NoCredentialsError) as e:
            print(colored_text(f"❌ AWS 호출 실패 (describe_regions): {e}", Colors.ERROR))
            return []

    def list_instances(self, region: str, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"instances_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                _cache.start_background_refresh(cache_key, self._fetch_instances, region)
                return cached_data

        instances = self._fetch_instances(region)
        _cache.set(cache_key, instances)
        return instances

    def _fetch_instances(self, region: str) -> List[Dict]:
        try:
            ec2 = self.session.client('ec2', region_name=region)
            insts = []
            next_token = None
            seen_tokens: set = set()
            page_count = 0

            while page_count < Config.MAX_PAGINATION_PAGES:
                page_count += 1
                params: Dict[str, Any] = {
                    'Filters': [{'Name': 'instance-state-name', 'Values': ['running']}],
                    'MaxResults': Config.EC2_PAGE_SIZE,
                }
                if next_token:
                    if next_token in seen_tokens:
                        logging.warning(f"페이지네이션 중복 토큰 감지, 종료 (region={region})")
                        break
                    seen_tokens.add(next_token)
                    params['NextToken'] = next_token

                resp = ec2.describe_instances(**params)
                for res in resp.get('Reservations', []):
                    for i in res.get('Instances', []):
                        insts.append(i)

                next_token = resp.get('NextToken')
                if not next_token:
                    break

            if page_count >= Config.MAX_PAGINATION_PAGES:
                logging.warning(f"페이지네이션 제한 초과 (region={region})")

            return insts
        except ClientError as e:
            logging.error(f"AWS list_instances 실패({region}): {e}")
            return []

    def list_instances_multi_region(self, regions: List[str], force_refresh: bool = False) -> List[Dict]:
        all_instances: List[Dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {
                ex.submit(self.list_instances, region, force_refresh): region
                for region in regions
            }
            for future in concurrent.futures.as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    for inst in future.result():
                        inst['_region'] = region
                        all_instances.append(inst)
                except Exception as e:
                    logging.warning(f"리전 {region} 인스턴스 검색 실패: {e}")
        return all_instances

    def list_ssm_managed(self, region: str, jump_host_tags: Optional[Dict] = None) -> List[Dict]:
        cache_key = f"ssm_{self.profile}_{region}_{str(jump_host_tags)}"
        cached_data = _cache.get(cache_key)
        if cached_data:
            return cached_data

        try:
            ssm = self.session.client('ssm', region_name=region)
            info: List[Dict] = []
            next_token = None
            seen_tokens: set = set()
            page_count = 0

            while page_count < Config.MAX_PAGINATION_PAGES:
                page_count += 1
                params: Dict[str, Any] = {'MaxResults': 50}
                if next_token:
                    if next_token in seen_tokens:
                        logging.warning("SSM 페이지네이션 중복 토큰 감지")
                        break
                    seen_tokens.add(next_token)
                    params['NextToken'] = next_token

                response = ssm.describe_instance_information(**params)
                info.extend(response.get('InstanceInformationList', []))
                next_token = response.get('NextToken')
                if not next_token:
                    break

            instance_ids = [i['InstanceId'] for i in info]
            if not instance_ids:
                return []

            ec2 = self.session.client('ec2', region_name=region)
            resp = ec2.describe_instances(InstanceIds=instance_ids)

            ssm_instances: List[Dict] = []
            for res in resp.get('Reservations', []):
                for i in res.get('Instances', []):
                    if jump_host_tags:
                        instance_tags = {t['Key']: t['Value'] for t in i.get('Tags', [])}
                        if not all(instance_tags.get(k) == v for k, v in jump_host_tags.items()):
                            continue
                    name = next((t['Value'] for t in i.get('Tags', []) if t['Key'] == 'Name'), '')
                    ssm_instances.append({'Id': i['InstanceId'], 'Name': name})

            result = sorted(ssm_instances, key=lambda x: x['Name'])
            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ssm_managed): {e}", Colors.ERROR))
            return []

    # -------------------------------------------------------------------------
    # RDS
    # -------------------------------------------------------------------------

    def get_rds_endpoints(self, region: str, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"rds_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            rds = self.session.client('rds', region_name=region)
            dbs = rds.describe_db_instances().get('DBInstances', [])
            result = [
                {
                    'Id': d['DBInstanceIdentifier'],
                    'Engine': d['Engine'],
                    'Endpoint': d['Endpoint']['Address'],
                    'Port': d['Endpoint']['Port'],
                    'DBName': d.get('DBName'),
                }
                for d in dbs
            ]
            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (describe_db_instances): {e}", Colors.ERROR))
            return []

    def get_rds_endpoints_multi_region(self, regions: List[str], force_refresh: bool = False) -> List[Dict]:
        all_dbs: List[Dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {
                ex.submit(self.get_rds_endpoints, region, force_refresh): region
                for region in regions
            }
            for future in concurrent.futures.as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    for db in future.result():
                        db['_region'] = region
                        all_dbs.append(db)
                except Exception as e:
                    logging.warning(f"리전 {region} RDS 검색 실패: {e}")
        return all_dbs

    # -------------------------------------------------------------------------
    # ElastiCache
    # -------------------------------------------------------------------------

    def list_cache_clusters(self, region: str, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"elasticache_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            ec = self.session.client('elasticache', region_name=region)
            clus = ec.describe_cache_clusters(ShowCacheNodeInfo=True).get('CacheClusters', [])
            result = []
            for c in clus:
                ep = c.get('ConfigurationEndpoint') or (
                    c.get('CacheNodes')[0].get('Endpoint') if c.get('CacheNodes') else {}
                )
                result.append({
                    'Id': c['CacheClusterId'],
                    'Engine': c['Engine'],
                    'Address': ep.get('Address', ''),
                    'Port': ep.get('Port', 0),
                })
            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (describe_cache_clusters): {e}", Colors.ERROR))
            return []

    def list_cache_clusters_multi_region(self, regions: List[str], force_refresh: bool = False) -> List[Dict]:
        all_clusters: List[Dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_region = {
                ex.submit(self.list_cache_clusters, region, force_refresh): region
                for region in regions
            }
            for future in concurrent.futures.as_completed(future_to_region):
                region = future_to_region[future]
                try:
                    for cluster in future.result():
                        cluster['_region'] = region
                        all_clusters.append(cluster)
                except Exception as e:
                    logging.warning(f"리전 {region} ElastiCache 검색 실패: {e}")
        return all_clusters

    # -------------------------------------------------------------------------
    # ECS
    # -------------------------------------------------------------------------

    def list_ecs_clusters(self, region: str, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"ecs_clusters_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            ecs = self.session.client('ecs', region_name=region)
            clusters = ecs.list_clusters().get('clusterArns', [])
            if not clusters:
                return []

            cluster_details = ecs.describe_clusters(clusters=clusters).get('clusters', [])
            result = [
                {
                    'Name': c['clusterName'],
                    'Arn': c['clusterArn'],
                    'Status': c['status'],
                    'RunningTasks': c['runningTasksCount'],
                    'ActiveServices': c['activeServicesCount'],
                }
                for c in cluster_details
            ]
            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ecs_clusters): {e}", Colors.ERROR))
            return []

    def list_ecs_services(self, region: str, cluster_name: str, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"ecs_services_{self.profile}_{region}_{cluster_name}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            ecs = self.session.client('ecs', region_name=region)
            services = ecs.list_services(cluster=cluster_name).get('serviceArns', [])
            if not services:
                return []

            service_details = ecs.describe_services(cluster=cluster_name, services=services).get('services', [])
            result = [
                {
                    'Name': s['serviceName'],
                    'Arn': s['serviceArn'],
                    'Status': s['status'],
                    'RunningCount': s['runningCount'],
                    'DesiredCount': s['desiredCount'],
                    'LaunchType': s.get('launchType', 'EC2'),
                    'PlatformVersion': s.get('platformVersion', 'LATEST'),
                }
                for s in service_details
            ]
            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ecs_services): {e}", Colors.ERROR))
            return []

    def list_ecs_tasks(self, region: str, cluster_name: str,
                       service_name: Optional[str] = None, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"ecs_tasks_{self.profile}_{region}_{cluster_name}_{service_name or 'all'}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            ecs = self.session.client('ecs', region_name=region)
            list_params: Dict[str, Any] = {'cluster': cluster_name}
            if service_name:
                list_params['serviceName'] = service_name

            tasks = ecs.list_tasks(**list_params).get('taskArns', [])
            if not tasks:
                return []

            task_details = ecs.describe_tasks(cluster=cluster_name, tasks=tasks).get('tasks', [])
            task_definitions: Dict = {}
            for task in task_details:
                task_def_arn = task['taskDefinitionArn']
                if task_def_arn not in task_definitions:
                    try:
                        task_def = ecs.describe_task_definition(taskDefinition=task_def_arn)
                        task_definitions[task_def_arn] = task_def['taskDefinition']
                    except ClientError:
                        task_definitions[task_def_arn] = None

            result = []
            for task in task_details:
                task_def = task_definitions.get(task['taskDefinitionArn'])
                containers = []
                if task_def:
                    containers = [
                        {
                            'Name': container['name'],
                            'Image': container['image'],
                            'Status': next(
                                (c['lastStatus'] for c in task.get('containers', [])
                                 if c['name'] == container['name']), 'UNKNOWN'
                            ),
                        }
                        for container in task_def.get('containerDefinitions', [])
                    ]
                result.append({
                    'TaskArn': task['taskArn'],
                    'TaskDefinitionArn': task['taskDefinitionArn'],
                    'LastStatus': task['lastStatus'],
                    'DesiredStatus': task['desiredStatus'],
                    'LaunchType': task.get('launchType', 'EC2'),
                    'PlatformVersion': task.get('platformVersion', 'LATEST'),
                    'Containers': containers,
                    'EnableExecuteCommand': task.get('enableExecuteCommand', False),
                })

            _cache.set(cache_key, result, ttl_seconds=120)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_ecs_tasks): {e}", Colors.ERROR))
            return []

    def get_ecs_task_log_config(self, region: str, task_definition_arn: str) -> List[Dict]:
        try:
            ecs = self.session.client('ecs', region_name=region)
            task_def = ecs.describe_task_definition(taskDefinition=task_definition_arn)
            container_defs = task_def.get('taskDefinition', {}).get('containerDefinitions', [])

            log_configs = []
            for container in container_defs:
                log_config = container.get('logConfiguration', {})
                if log_config.get('logDriver') == 'awslogs':
                    options = log_config.get('options', {})
                    log_configs.append({
                        'ContainerName': container['name'],
                        'LogGroup': options.get('awslogs-group', ''),
                        'LogStreamPrefix': options.get('awslogs-stream-prefix', ''),
                        'Region': options.get('awslogs-region', region),
                    })
            return log_configs
        except ClientError as e:
            logging.warning(f"태스크 정의 로그 설정 조회 실패: {e}")
            return []

    def get_ecs_log_streams(self, region: str, log_group: str,
                             log_stream_prefix: str, task_id: str) -> List[str]:
        try:
            logs = self.session.client('logs', region_name=region)
            prefix = f"{log_stream_prefix}/" if log_stream_prefix else ""
            response = logs.describe_log_streams(
                logGroupName=log_group,
                logStreamNamePrefix=prefix,
                orderBy='LastEventTime',
                descending=True,
                limit=50,
            )
            return [
                stream.get('logStreamName', '')
                for stream in response.get('logStreams', [])
                if task_id in stream.get('logStreamName', '')
            ]
        except ClientError as e:
            logging.warning(f"로그 스트림 조회 실패: {e}")
            return []

    def get_ecs_container_logs(self, region: str, log_group: str, log_stream: str,
                                start_time: Optional[int] = None, limit: int = 100) -> List[Dict]:
        try:
            logs = self.session.client('logs', region_name=region)
            params: Dict[str, Any] = {
                'logGroupName': log_group,
                'logStreamName': log_stream,
                'limit': limit,
                'startFromHead': False,
            }
            if start_time:
                params['startTime'] = start_time

            response = logs.get_log_events(**params)
            return [
                {
                    'timestamp': event.get('timestamp', 0),
                    'message': event.get('message', ''),
                    'ingestionTime': event.get('ingestionTime', 0),
                }
                for event in response.get('events', [])
            ]
        except ClientError as e:
            logging.warning(f"로그 조회 실패: {e}")
            return []

    # -------------------------------------------------------------------------
    # EKS
    # -------------------------------------------------------------------------

    def list_eks_clusters(self, region: str, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"eks_clusters_{self.profile}_{region}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            eks = self.session.client('eks', region_name=region)
            cluster_names = eks.list_clusters().get('clusters', [])
            if not cluster_names:
                return []

            result = []
            for name in cluster_names:
                try:
                    detail = eks.describe_cluster(name=name).get('cluster', {})
                    result.append({
                        'Name': detail.get('name', name),
                        'Arn': detail.get('arn', ''),
                        'Status': detail.get('status', 'UNKNOWN'),
                        'Version': detail.get('version', 'N/A'),
                        'Endpoint': detail.get('endpoint', ''),
                        'PlatformVersion': detail.get('platformVersion', 'N/A'),
                        'CreatedAt': detail.get('createdAt'),
                    })
                except ClientError as e:
                    logging.warning(f"EKS 클러스터 {name} 상세 조회 실패: {e}")
                    result.append({'Name': name, 'Status': 'UNKNOWN', 'Version': 'N/A'})

            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_eks_clusters): {e}", Colors.ERROR))
            return []

    def get_eks_cluster_detail(self, region: str, cluster_name: str) -> Optional[Dict]:
        cache_key = f"eks_cluster_detail_{self.profile}_{region}_{cluster_name}"
        cached_data = _cache.get(cache_key)
        if cached_data:
            return cached_data

        try:
            eks = self.session.client('eks', region_name=region)
            detail = eks.describe_cluster(name=cluster_name).get('cluster', {})
            vpc = detail.get('resourcesVpcConfig', {})
            result = {
                'Name': detail.get('name', cluster_name),
                'Arn': detail.get('arn', ''),
                'Status': detail.get('status', 'UNKNOWN'),
                'Version': detail.get('version', 'N/A'),
                'Endpoint': detail.get('endpoint', ''),
                'PlatformVersion': detail.get('platformVersion', 'N/A'),
                'RoleArn': detail.get('roleArn', ''),
                'VpcId': vpc.get('vpcId', ''),
                'SubnetIds': vpc.get('subnetIds', []),
                'SecurityGroupIds': vpc.get('securityGroupIds', []),
                'ClusterSecurityGroupId': vpc.get('clusterSecurityGroupId', ''),
                'EndpointPublicAccess': vpc.get('endpointPublicAccess', False),
                'EndpointPrivateAccess': vpc.get('endpointPrivateAccess', False),
                'CreatedAt': detail.get('createdAt'),
                'Tags': detail.get('tags', {}),
            }
            _cache.set(cache_key, result, ttl_seconds=300)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (get_eks_cluster_detail): {e}", Colors.ERROR))
            return None

    def list_eks_nodegroups(self, region: str, cluster_name: str, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"eks_nodegroups_{self.profile}_{region}_{cluster_name}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            eks = self.session.client('eks', region_name=region)
            nodegroup_names = eks.list_nodegroups(clusterName=cluster_name).get('nodegroups', [])
            if not nodegroup_names:
                return []

            result = []
            for ng_name in nodegroup_names:
                try:
                    detail = eks.describe_nodegroup(
                        clusterName=cluster_name, nodegroupName=ng_name
                    ).get('nodegroup', {})
                    scaling = detail.get('scalingConfig', {})
                    result.append({
                        'Name': detail.get('nodegroupName', ng_name),
                        'Status': detail.get('status', 'UNKNOWN'),
                        'InstanceTypes': detail.get('instanceTypes', []),
                        'AmiType': detail.get('amiType', 'N/A'),
                        'CapacityType': detail.get('capacityType', 'ON_DEMAND'),
                        'DesiredSize': scaling.get('desiredSize', 0),
                        'MinSize': scaling.get('minSize', 0),
                        'MaxSize': scaling.get('maxSize', 0),
                        'NodeRole': detail.get('nodeRole', ''),
                    })
                except ClientError as e:
                    logging.warning(f"노드그룹 {ng_name} 상세 조회 실패: {e}")

            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_eks_nodegroups): {e}", Colors.ERROR))
            return []

    def list_eks_fargate_profiles(self, region: str, cluster_name: str, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"eks_fargate_{self.profile}_{region}_{cluster_name}"
        if not force_refresh:
            cached_data = _cache.get(cache_key)
            if cached_data:
                return cached_data

        try:
            eks = self.session.client('eks', region_name=region)
            profile_names = eks.list_fargate_profiles(clusterName=cluster_name).get('fargateProfileNames', [])
            if not profile_names:
                return []

            result = []
            for fp_name in profile_names:
                try:
                    detail = eks.describe_fargate_profile(
                        clusterName=cluster_name, fargateProfileName=fp_name
                    ).get('fargateProfile', {})
                    namespaces = [s.get('namespace', '') for s in detail.get('selectors', [])]
                    result.append({
                        'Name': detail.get('fargateProfileName', fp_name),
                        'Status': detail.get('status', 'UNKNOWN'),
                        'PodExecutionRoleArn': detail.get('podExecutionRoleArn', ''),
                        'Namespaces': namespaces,
                        'Subnets': detail.get('subnets', []),
                    })
                except ClientError as e:
                    logging.warning(f"Fargate 프로필 {fp_name} 상세 조회 실패: {e}")

            _cache.set(cache_key, result)
            return result
        except ClientError as e:
            print(colored_text(f"❌ AWS 호출 실패 (list_eks_fargate_profiles): {e}", Colors.ERROR))
            return []

    # -------------------------------------------------------------------------
    # CloudWatch
    # -------------------------------------------------------------------------

    def list_cloudwatch_dashboards(self, region: str, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"cloudwatch_dashboards_{self.profile}_{region}"
        if not force_refresh:
            cached = _cache.get(cache_key)
            if cached:
                return cached

        try:
            cw = self.session.client('cloudwatch', region_name=region)
            dashboards: List[Dict] = []
            paginator = cw.get_paginator('list_dashboards')
            for page in paginator.paginate():
                for entry in page.get('DashboardEntries', []):
                    dashboards.append({
                        'DashboardName': entry.get('DashboardName', ''),
                        'DashboardArn': entry.get('DashboardArn', ''),
                        'LastModified': entry.get('LastModified'),
                        'Size': entry.get('Size', 0),
                    })
            _cache.set(cache_key, dashboards)
            return dashboards
        except ClientError as e:
            logging.warning(f"CloudWatch 대시보드 조회 실패: {e}")
            return []

    def list_cloudwatch_alarms(self, region: str, state: Optional[str] = None,
                               force_refresh: bool = False) -> List[Dict]:
        cache_key = f"cloudwatch_alarms_{self.profile}_{region}_{state or 'all'}"
        if not force_refresh:
            cached = _cache.get(cache_key)
            if cached:
                return cached

        try:
            cw = self.session.client('cloudwatch', region_name=region)
            alarms: List[Dict] = []
            paginator = cw.get_paginator('describe_alarms')
            params: Dict[str, Any] = {}
            if state:
                params['StateValue'] = state

            for page in paginator.paginate(**params):
                for alarm in page.get('MetricAlarms', []):
                    alarms.append({
                        'AlarmName': alarm.get('AlarmName', ''),
                        'AlarmArn': alarm.get('AlarmArn', ''),
                        'StateValue': alarm.get('StateValue', ''),
                        'StateReason': alarm.get('StateReason', ''),
                        'MetricName': alarm.get('MetricName', ''),
                        'Namespace': alarm.get('Namespace', ''),
                        'Threshold': alarm.get('Threshold', 0),
                        'ComparisonOperator': alarm.get('ComparisonOperator', ''),
                        'EvaluationPeriods': alarm.get('EvaluationPeriods', 0),
                        'StateUpdatedTimestamp': alarm.get('StateUpdatedTimestamp'),
                    })
                for alarm in page.get('CompositeAlarms', []):
                    alarms.append({
                        'AlarmName': alarm.get('AlarmName', ''),
                        'AlarmArn': alarm.get('AlarmArn', ''),
                        'StateValue': alarm.get('StateValue', ''),
                        'StateReason': alarm.get('StateReason', ''),
                        'MetricName': '[Composite]',
                        'Namespace': '',
                        'Threshold': 0,
                        'ComparisonOperator': '',
                        'EvaluationPeriods': 0,
                        'StateUpdatedTimestamp': alarm.get('StateUpdatedTimestamp'),
                    })
            _cache.set(cache_key, alarms)
            return alarms
        except ClientError as e:
            logging.warning(f"CloudWatch 알람 조회 실패: {e}")
            return []

    def get_alarm_history(self, region: str, alarm_name: str, limit: int = 50) -> List[Dict]:
        try:
            cw = self.session.client('cloudwatch', region_name=region)
            response = cw.describe_alarm_history(
                AlarmName=alarm_name,
                HistoryItemType='StateUpdate',
                MaxRecords=limit,
            )
            return [
                {
                    'Timestamp': item.get('Timestamp'),
                    'HistorySummary': item.get('HistorySummary', ''),
                    'HistoryItemType': item.get('HistoryItemType', ''),
                    'HistoryData': item.get('HistoryData', ''),
                }
                for item in response.get('AlarmHistoryItems', [])
            ]
        except ClientError as e:
            logging.warning(f"알람 히스토리 조회 실패: {e}")
            return []

    def list_log_groups(self, region: str, prefix: Optional[str] = None,
                        force_refresh: bool = False) -> List[Dict]:
        cache_key = f"cloudwatch_logs_{self.profile}_{region}_{prefix or 'all'}"
        if not force_refresh:
            cached = _cache.get(cache_key)
            if cached:
                return cached

        try:
            logs = self.session.client('logs', region_name=region)
            log_groups: List[Dict] = []
            paginator = logs.get_paginator('describe_log_groups')
            params: Dict[str, Any] = {}
            if prefix:
                params['logGroupNamePrefix'] = prefix

            for page in paginator.paginate(**params):
                for lg in page.get('logGroups', []):
                    log_groups.append({
                        'logGroupName': lg.get('logGroupName', ''),
                        'logGroupArn': lg.get('arn', ''),
                        'creationTime': lg.get('creationTime', 0),
                        'storedBytes': lg.get('storedBytes', 0),
                        'retentionInDays': lg.get('retentionInDays'),
                    })
            _cache.set(cache_key, log_groups)
            return log_groups
        except ClientError as e:
            logging.warning(f"로그 그룹 조회 실패: {e}")
            return []

    def get_log_streams(self, region: str, log_group: str, limit: int = 50) -> List[Dict]:
        try:
            logs = self.session.client('logs', region_name=region)
            response = logs.describe_log_streams(
                logGroupName=log_group,
                orderBy='LastEventTime',
                descending=True,
                limit=limit,
            )
            return [
                {
                    'logStreamName': stream.get('logStreamName', ''),
                    'creationTime': stream.get('creationTime', 0),
                    'lastEventTimestamp': stream.get('lastEventTimestamp', 0),
                    'lastIngestionTime': stream.get('lastIngestionTime', 0),
                    'storedBytes': stream.get('storedBytes', 0),
                }
                for stream in response.get('logStreams', [])
            ]
        except ClientError as e:
            logging.warning(f"로그 스트림 조회 실패: {e}")
            return []

    def filter_log_events(self, region: str, log_group: str,
                          log_stream: Optional[str] = None,
                          filter_pattern: Optional[str] = None,
                          start_time: Optional[int] = None,
                          end_time: Optional[int] = None,
                          limit: int = 100) -> List[Dict]:
        try:
            logs = self.session.client('logs', region_name=region)
            params: Dict[str, Any] = {'logGroupName': log_group, 'limit': limit}
            if log_stream:
                params['logStreamNames'] = [log_stream]
            if filter_pattern:
                params['filterPattern'] = filter_pattern
            if start_time:
                params['startTime'] = start_time
            if end_time:
                params['endTime'] = end_time

            response = logs.filter_log_events(**params)
            return [
                {
                    'timestamp': event.get('timestamp', 0),
                    'message': event.get('message', ''),
                    'logStreamName': event.get('logStreamName', ''),
                    'ingestionTime': event.get('ingestionTime', 0),
                }
                for event in response.get('events', [])
            ]
        except ClientError as e:
            logging.warning(f"로그 이벤트 필터 조회 실패: {e}")
            return []

    # -------------------------------------------------------------------------
    # Lambda
    # -------------------------------------------------------------------------

    def list_lambda_functions(self, region: str, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"lambda_functions_{self.profile}_{region}"
        if not force_refresh:
            cached = _cache.get(cache_key)
            if cached:
                return cached

        try:
            lambda_client = self.session.client('lambda', region_name=region)
            functions: List[Dict] = []
            paginator = lambda_client.get_paginator('list_functions')
            for page in paginator.paginate():
                for func in page.get('Functions', []):
                    functions.append({
                        'FunctionName': func.get('FunctionName', ''),
                        'FunctionArn': func.get('FunctionArn', ''),
                        'Runtime': func.get('Runtime', 'N/A'),
                        'Handler': func.get('Handler', ''),
                        'MemorySize': func.get('MemorySize', 0),
                        'Timeout': func.get('Timeout', 0),
                        'CodeSize': func.get('CodeSize', 0),
                        'Description': func.get('Description', ''),
                        'LastModified': func.get('LastModified', ''),
                        'State': func.get('State', 'Active'),
                        'PackageType': func.get('PackageType', 'Zip'),
                    })
            _cache.set(cache_key, functions)
            return functions
        except ClientError as e:
            logging.warning(f"Lambda 함수 목록 조회 실패: {e}")
            return []

    def get_lambda_function_detail(self, region: str, function_name: str) -> Optional[Dict]:
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            response = lambda_client.get_function(FunctionName=function_name)
            config = response.get('Configuration', {})
            code = response.get('Code', {})
            return {
                'FunctionName': config.get('FunctionName', ''),
                'FunctionArn': config.get('FunctionArn', ''),
                'Runtime': config.get('Runtime', 'N/A'),
                'Role': config.get('Role', ''),
                'Handler': config.get('Handler', ''),
                'CodeSize': config.get('CodeSize', 0),
                'Description': config.get('Description', ''),
                'Timeout': config.get('Timeout', 0),
                'MemorySize': config.get('MemorySize', 0),
                'LastModified': config.get('LastModified', ''),
                'Version': config.get('Version', ''),
                'State': config.get('State', ''),
                'StateReason': config.get('StateReason', ''),
                'Environment': config.get('Environment', {}).get('Variables', {}),
                'VpcConfig': config.get('VpcConfig', {}),
                'Layers': [layer.get('Arn', '') for layer in config.get('Layers', [])],
                'CodeLocation': code.get('Location', ''),
                'RepositoryType': code.get('RepositoryType', ''),
            }
        except ClientError as e:
            logging.warning(f"Lambda 함수 상세 조회 실패: {e}")
            return None

    def invoke_lambda_function(self, region: str, function_name: str,
                               payload: Optional[Dict] = None,
                               invocation_type: str = 'RequestResponse') -> Dict:
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            params: Dict[str, Any] = {
                'FunctionName': function_name,
                'InvocationType': invocation_type,
                'LogType': 'Tail',
                'Payload': json.dumps(payload) if payload else '{}',
            }
            response = lambda_client.invoke(**params)

            response_payload = response.get('Payload')
            if response_payload:
                payload_str = response_payload.read().decode('utf-8')
                try:
                    response_data = json.loads(payload_str)
                except json.JSONDecodeError:
                    response_data = payload_str
            else:
                response_data = None

            log_result = response.get('LogResult', '')
            if log_result:
                log_result = base64.b64decode(log_result).decode('utf-8')

            return {
                'StatusCode': response.get('StatusCode', 0),
                'FunctionError': response.get('FunctionError'),
                'ExecutedVersion': response.get('ExecutedVersion', ''),
                'Payload': response_data,
                'LogResult': log_result,
            }
        except ClientError as e:
            logging.warning(f"Lambda 함수 실행 실패: {e}")
            return {'StatusCode': 0, 'FunctionError': str(e), 'ExecutedVersion': '', 'Payload': None, 'LogResult': ''}

    def get_lambda_function_logs(self, region: str, function_name: str,
                                 hours: int = 1, limit: int = 100) -> List[Dict]:
        log_group = f"/aws/lambda/{function_name}"
        start_time = int((time.time() - hours * 3600) * 1000)
        return self.filter_log_events(region=region, log_group=log_group, start_time=start_time, limit=limit)

    def list_lambda_versions(self, region: str, function_name: str) -> List[Dict]:
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            response = lambda_client.list_versions_by_function(FunctionName=function_name)
            return [
                {
                    'Version': ver.get('Version', ''),
                    'Description': ver.get('Description', ''),
                    'FunctionArn': ver.get('FunctionArn', ''),
                    'LastModified': ver.get('LastModified', ''),
                }
                for ver in response.get('Versions', [])
            ]
        except ClientError as e:
            logging.warning(f"Lambda 버전 조회 실패: {e}")
            return []

    def list_lambda_aliases(self, region: str, function_name: str) -> List[Dict]:
        try:
            lambda_client = self.session.client('lambda', region_name=region)
            response = lambda_client.list_aliases(FunctionName=function_name)
            return [
                {
                    'Name': alias.get('Name', ''),
                    'FunctionVersion': alias.get('FunctionVersion', ''),
                    'Description': alias.get('Description', ''),
                    'AliasArn': alias.get('AliasArn', ''),
                }
                for alias in response.get('Aliases', [])
            ]
        except ClientError as e:
            logging.warning(f"Lambda 별칭 조회 실패: {e}")
            return []

    # -------------------------------------------------------------------------
    # S3
    # -------------------------------------------------------------------------

    def list_s3_buckets(self, force_refresh: bool = False) -> List[Dict]:
        cache_key = f"s3_buckets_{self.profile}"
        if not force_refresh:
            cached = _cache.get(cache_key)
            if cached:
                return cached

        try:
            s3 = self.session.client('s3')
            response = s3.list_buckets()
            buckets = [
                {'Name': bucket.get('Name', ''), 'CreationDate': bucket.get('CreationDate')}
                for bucket in response.get('Buckets', [])
            ]
            _cache.set(cache_key, buckets)
            return buckets
        except ClientError as e:
            logging.warning(f"S3 버킷 목록 조회 실패: {e}")
            return []

    def get_bucket_location(self, bucket_name: str) -> str:
        try:
            s3 = self.session.client('s3')
            response = s3.get_bucket_location(Bucket=bucket_name)
            location = response.get('LocationConstraint')
            return location if location else 'us-east-1'
        except ClientError as e:
            logging.warning(f"버킷 리전 조회 실패: {e}")
            return 'unknown'

    def list_s3_objects(self, bucket_name: str, prefix: str = "",
                        delimiter: str = "/", max_keys: int = 100) -> Dict:
        try:
            s3 = self.session.client('s3')
            response = s3.list_objects_v2(
                Bucket=bucket_name, Prefix=prefix, Delimiter=delimiter, MaxKeys=max_keys
            )
            folders = [
                {'Key': cp.get('Prefix', ''), 'Type': 'folder', 'Size': 0, 'LastModified': None}
                for cp in response.get('CommonPrefixes', [])
            ]
            files = [
                {
                    'Key': obj.get('Key', ''),
                    'Type': 'file',
                    'Size': obj.get('Size', 0),
                    'LastModified': obj.get('LastModified'),
                    'StorageClass': obj.get('StorageClass', 'STANDARD'),
                }
                for obj in response.get('Contents', [])
                if obj.get('Key') != prefix
            ]
            return {
                'folders': folders,
                'files': files,
                'IsTruncated': response.get('IsTruncated', False),
                'NextContinuationToken': response.get('NextContinuationToken'),
            }
        except ClientError as e:
            logging.warning(f"S3 객체 목록 조회 실패: {e}")
            return {'folders': [], 'files': [], 'IsTruncated': False, 'NextContinuationToken': None}

    def get_s3_object_info(self, bucket_name: str, key: str) -> Optional[Dict]:
        try:
            s3 = self.session.client('s3')
            response = s3.head_object(Bucket=bucket_name, Key=key)
            return {
                'Key': key,
                'ContentLength': response.get('ContentLength', 0),
                'ContentType': response.get('ContentType', ''),
                'LastModified': response.get('LastModified'),
                'ETag': response.get('ETag', ''),
                'StorageClass': response.get('StorageClass', 'STANDARD'),
                'Metadata': response.get('Metadata', {}),
            }
        except ClientError as e:
            logging.warning(f"S3 객체 정보 조회 실패: {e}")
            return None

    def download_s3_object(self, bucket_name: str, key: str, local_path: str,
                           progress_callback: Optional[Callable] = None) -> bool:
        try:
            s3 = self.session.client('s3')
            callback = None
            if progress_callback:
                class ProgressPercentage:
                    def __init__(self, client, bucket, key, callback_func):
                        self._size = client.head_object(Bucket=bucket, Key=key)['ContentLength']
                        self._seen_so_far = 0
                        self._callback = callback_func

                    def __call__(self, bytes_amount):
                        self._seen_so_far += bytes_amount
                        self._callback(self._seen_so_far, self._size, (self._seen_so_far / self._size) * 100)

                callback = ProgressPercentage(s3, bucket_name, key, progress_callback)

            s3.download_file(bucket_name, key, local_path, Callback=callback)
            return True
        except (ClientError, Exception) as e:
            logging.warning(f"S3 다운로드 실패: {e}")
            return False

    def upload_s3_object(self, local_path: str, bucket_name: str, key: str,
                         progress_callback: Optional[Callable] = None) -> bool:
        try:
            s3 = self.session.client('s3')
            callback = None
            if progress_callback:
                file_size = os.path.getsize(local_path)

                class ProgressPercentage:
                    def __init__(self, size, callback_func):
                        self._size = size
                        self._seen_so_far = 0
                        self._callback = callback_func

                    def __call__(self, bytes_amount):
                        self._seen_so_far += bytes_amount
                        self._callback(self._seen_so_far, self._size, (self._seen_so_far / self._size) * 100)

                callback = ProgressPercentage(file_size, progress_callback)

            s3.upload_file(local_path, bucket_name, key, Callback=callback)
            return True
        except (ClientError, Exception) as e:
            logging.warning(f"S3 업로드 실패: {e}")
            return False

    def generate_presigned_url(self, bucket_name: str, key: str, expiration: int = 3600) -> Optional[str]:
        try:
            s3 = self.session.client('s3')
            return s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': key},
                ExpiresIn=expiration,
            )
        except ClientError as e:
            logging.warning(f"Presigned URL 생성 실패: {e}")
            return None

    def delete_s3_object(self, bucket_name: str, key: str) -> bool:
        try:
            s3 = self.session.client('s3')
            s3.delete_object(Bucket=bucket_name, Key=key)
            return True
        except ClientError as e:
            logging.warning(f"S3 객체 삭제 실패: {e}")
            return False
