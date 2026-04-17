"""EKS 클러스터 관리 메뉴"""
from __future__ import annotations

import time

from ec2menu.core.colors import Colors, colored_text, get_status_color
from ec2menu.terminal.kubectl import (
    check_kubectl_installed,
    check_kubeconfig_exists,
    get_kubectl_namespaces,
    get_kubectl_pods,
    launch_kubectl_exec,
    launch_kubectl_logs,
    update_kubeconfig,
)
from ec2menu.ui.menu import interactive_select

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ec2menu.aws.manager import AWSManager


def eks_menu(manager: AWSManager, region: str) -> None:
    kubectl_available = check_kubectl_installed()

    while True:
        if region == 'multi-region':
            regions = manager.list_regions()
            all_clusters = []
            print(colored_text("⏳ 모든 리전에서 EKS 클러스터 검색 중...", Colors.INFO))
            for r in regions:
                try:
                    clusters_in_region = manager.list_eks_clusters(r)
                    for c in clusters_in_region:
                        c['_region'] = r
                    all_clusters.extend(clusters_in_region)
                except Exception:
                    pass
            clusters = all_clusters
        else:
            clusters = manager.list_eks_clusters(region)
            for c in clusters:
                c['_region'] = region

        if not clusters:
            print(colored_text(f"\n⚠ 리전 {region}에 EKS 클러스터가 없습니다.", Colors.WARNING))
            return

        if not kubectl_available:
            print(colored_text("\n⚠ kubectl 미설치 - Pod 관련 기능 비활성화", Colors.WARNING))

        cluster_items = []
        for cluster in clusters:
            version = cluster.get('Version', 'N/A')
            cluster_region = cluster.get('_region', region)
            if region == 'multi-region':
                item = f"{cluster['Name']:<30} {cluster['Status']:<10} K8s: {version:<8} [{cluster_region}]"
            else:
                item = f"{cluster['Name']:<30} {cluster['Status']:<10} K8s: {version}"
            cluster_items.append(item)
        cluster_items.append("🔙 돌아가기")

        region_display = "All Regions" if region == 'multi-region' else region
        title = f"EKS Clusters  │  Region: {region_display}  │  {len(clusters)} clusters"
        cluster_sel = interactive_select(cluster_items, title=title)

        if cluster_sel == -1 or cluster_sel == len(clusters):
            return

        selected_cluster = clusters[cluster_sel]
        cluster_name = selected_cluster['Name']
        cluster_region = selected_cluster.get('_region', region)

        while True:
            sub_items = [
                "📊 클러스터 상세 정보",
                "🖥️ 노드그룹 목록",
                "🚀 Fargate 프로필",
                "⚙️ kubeconfig 설정",
            ]
            if kubectl_available:
                sub_items.extend([
                    "📦 Pod 목록 조회",
                    "📋 Pod 로그 조회",
                    "🔗 Pod exec 접속",
                ])
            else:
                sub_items.extend([
                    "📦 Pod 목록 조회 (kubectl 필요)",
                    "📋 Pod 로그 조회 (kubectl 필요)",
                    "🔗 Pod exec 접속 (kubectl 필요)",
                ])
            sub_items.append("🔙 돌아가기")

            title = f"EKS: {cluster_name}  │  Region: {cluster_region}"
            sub_sel = interactive_select(sub_items, title=title, show_index=False)

            if sub_sel == -1 or sub_sel == len(sub_items) - 1:
                break

            if sub_sel == 0:
                detail = manager.get_eks_cluster_detail(cluster_region, cluster_name)
                if detail:
                    print(colored_text(f"\n--- [ Cluster Detail: {cluster_name} ] ---", Colors.HEADER))
                    print(f"  Name:            {detail['Name']}")
                    print(f"  Status:          {colored_text(detail['Status'], get_status_color(detail['Status']))}")
                    print(f"  Version:         {detail['Version']}")
                    print(f"  Platform:        {detail['PlatformVersion']}")
                    endpoint = detail.get('Endpoint', 'N/A')
                    print(f"  Endpoint:        {endpoint[:60]}..." if len(endpoint) > 60 else f"  Endpoint:        {endpoint}")
                    print(f"  VPC:             {detail['VpcId']}")
                    print(f"  Public Access:   {'Yes' if detail['EndpointPublicAccess'] else 'No'}")
                    print(f"  Private Access:  {'Yes' if detail['EndpointPrivateAccess'] else 'No'}")
                    if detail.get('CreatedAt'):
                        print(f"  Created:         {detail['CreatedAt']}")
                    print("------------------------------------------\n")
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

            elif sub_sel == 1:
                nodegroups = manager.list_eks_nodegroups(cluster_region, cluster_name)
                if not nodegroups:
                    print(colored_text(f"\n⚠ 클러스터 {cluster_name}에 노드그룹이 없습니다.", Colors.WARNING))
                else:
                    print(colored_text(f"\n--- [ Node Groups in {cluster_name} ] ---", Colors.HEADER))
                    for idx, ng in enumerate(nodegroups, 1):
                        status_colored = colored_text(ng['Status'], get_status_color(ng['Status']))
                        instance_types = ', '.join(ng.get('InstanceTypes', ['N/A']))
                        scaling = f"{ng['DesiredSize']}/{ng['MinSize']}-{ng['MaxSize']}"
                        capacity = ng.get('CapacityType', 'ON_DEMAND')
                        print(f" {idx:2d}) {ng['Name']} ({status_colored})")
                        print(f"      Types: {instance_types} | Scaling: {scaling} | {capacity}")
                    print("------------------------------------------\n")
                input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

            elif sub_sel == 2:
                profiles = manager.list_eks_fargate_profiles(cluster_region, cluster_name)
                if not profiles:
                    print(colored_text(f"\n⚠ 클러스터 {cluster_name}에 Fargate 프로필이 없습니다.", Colors.WARNING))
                else:
                    print(colored_text(f"\n--- [ Fargate Profiles in {cluster_name} ] ---", Colors.HEADER))
                    for idx, fp in enumerate(profiles, 1):
                        status_colored = colored_text(fp['Status'], get_status_color(fp['Status']))
                        namespaces = ', '.join(fp.get('Namespaces', ['N/A']))
                        print(f" {idx:2d}) {fp['Name']} ({status_colored})")
                        print(f"      Namespaces: {namespaces}")
                    print("------------------------------------------\n")
                input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

            elif sub_sel == 3:
                update_kubeconfig(manager.profile, cluster_region, cluster_name)
                input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

            elif sub_sel == 4:
                if not kubectl_available:
                    print(colored_text("❌ kubectl이 설치되어 있지 않습니다.", Colors.ERROR))
                    print(colored_text("   설치 방법: brew install kubectl", Colors.INFO))
                    continue
                if not check_kubeconfig_exists(cluster_name):
                    print(colored_text(f"⚠ 클러스터 {cluster_name}의 kubeconfig가 없습니다.", Colors.WARNING))
                    update_sel = input(colored_text("kubeconfig를 설정하시겠습니까? (y/N): ", Colors.PROMPT)).strip().lower()
                    if update_sel == 'y':
                        if not update_kubeconfig(manager.profile, cluster_region, cluster_name):
                            continue
                    else:
                        continue
                namespaces = get_kubectl_namespaces()
                if not namespaces:
                    print(colored_text("❌ 네임스페이스 목록을 가져올 수 없습니다.", Colors.ERROR))
                    continue
                ns_items = namespaces + ["🔙 돌아가기"]
                ns_sel = interactive_select(ns_items, title="Namespace 선택")
                if ns_sel == -1 or ns_sel == len(namespaces):
                    continue
                selected_ns = namespaces[ns_sel]
                pods = get_kubectl_pods(selected_ns)
                if not pods:
                    print(colored_text(f"⚠ 네임스페이스 {selected_ns}에 Pod가 없습니다.", Colors.WARNING))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue
                pod_items = []
                for pod in pods:
                    pod_items.append(f"{pod['Name']:<45} {pod['Status']:<12} Ready:{pod['Ready']:<6} Restarts:{pod['Restarts']}")
                pod_items.append("🔙 돌아가기")
                pod_sel = interactive_select(pod_items, title=f"Pods in {selected_ns}")
                if pod_sel == -1 or pod_sel == len(pods):
                    continue
                selected_pod = pods[pod_sel]
                print(colored_text(f"\n--- [ Pod 상세: {selected_pod['Name']} ] ---", Colors.HEADER))
                print(f"  Name:      {selected_pod['Name']}")
                print(f"  Namespace: {selected_ns}")
                print(f"  Status:    {selected_pod['Status']}")
                print(f"  Ready:     {selected_pod['Ready']}")
                print(f"  Restarts:  {selected_pod['Restarts']}")
                print(f"  Age:       {selected_pod.get('Age', 'N/A')}")
                if selected_pod.get('Containers'):
                    print(f"  Containers: {', '.join(selected_pod['Containers'])}")
                print("----------------------------------------------")
                input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))

            elif sub_sel == 5:
                if not kubectl_available:
                    print(colored_text("❌ kubectl이 설치되어 있지 않습니다.", Colors.ERROR))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue
                if not check_kubeconfig_exists(cluster_name):
                    print(colored_text("⚠ 먼저 kubeconfig를 설정하세요.", Colors.WARNING))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue
                namespaces = get_kubectl_namespaces()
                if not namespaces:
                    continue
                ns_items = namespaces + ["🔙 돌아가기"]
                ns_sel = interactive_select(ns_items, title="Namespace 선택")
                if ns_sel == -1 or ns_sel == len(namespaces):
                    continue
                selected_ns = namespaces[ns_sel]
                pods = get_kubectl_pods(selected_ns)
                if not pods:
                    print(colored_text(f"⚠ 네임스페이스 {selected_ns}에 Pod가 없습니다.", Colors.WARNING))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue
                pod_items = [f"{pod['Name']:<40} {pod['Status']:<10}" for pod in pods]
                pod_items.append("🔙 돌아가기")
                pod_sel = interactive_select(pod_items, title=f"Pods in {selected_ns}")
                if pod_sel == -1 or pod_sel == len(pods):
                    continue
                selected_pod = pods[pod_sel]
                containers = selected_pod.get('Containers', [])
                selected_container = None
                if len(containers) > 1:
                    container_items = containers + ["🔙 돌아가기"]
                    c_sel = interactive_select(container_items, title="Container 선택")
                    if c_sel == -1 or c_sel == len(containers):
                        continue
                    selected_container = containers[c_sel]
                elif containers:
                    selected_container = containers[0]
                print(colored_text(f"\n📋 Pod '{selected_pod['Name']}' 로그를 새 터미널에서 엽니다...", Colors.INFO))
                launch_kubectl_logs(selected_pod['Name'], selected_ns, selected_container)
                print(colored_text("✅ 새 터미널에서 로그 스트리밍이 시작되었습니다.", Colors.SUCCESS))
                time.sleep(1)

            elif sub_sel == 6:
                if not kubectl_available:
                    print(colored_text("❌ kubectl이 설치되어 있지 않습니다.", Colors.ERROR))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue
                if not check_kubeconfig_exists(cluster_name):
                    print(colored_text("⚠ 먼저 kubeconfig를 설정하세요.", Colors.WARNING))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue
                namespaces = get_kubectl_namespaces()
                if not namespaces:
                    continue
                ns_items = namespaces + ["🔙 돌아가기"]
                ns_sel = interactive_select(ns_items, title="Namespace 선택")
                if ns_sel == -1 or ns_sel == len(namespaces):
                    continue
                selected_ns = namespaces[ns_sel]
                pods = get_kubectl_pods(selected_ns)
                if not pods:
                    print(colored_text(f"⚠ 네임스페이스 {selected_ns}에 Pod가 없습니다.", Colors.WARNING))
                    input(colored_text("계속하려면 Enter를 누르세요...", Colors.PROMPT))
                    continue
                pod_items = [f"{pod['Name']:<40} {pod['Status']:<10}" for pod in pods]
                pod_items.append("🔙 돌아가기")
                pod_sel = interactive_select(pod_items, title=f"Pods in {selected_ns}")
                if pod_sel == -1 or pod_sel == len(pods):
                    continue
                selected_pod = pods[pod_sel]
                containers = selected_pod.get('Containers', [])
                selected_container = None
                if len(containers) > 1:
                    container_items = containers + ["🔙 돌아가기"]
                    c_sel = interactive_select(container_items, title="Container 선택")
                    if c_sel == -1 or c_sel == len(containers):
                        continue
                    selected_container = containers[c_sel]
                elif containers:
                    selected_container = containers[0]
                print(colored_text(f"\n🔗 Pod '{selected_pod['Name']}'에 접속합니다...", Colors.INFO))
                launch_kubectl_exec(selected_pod['Name'], selected_ns, selected_container)
                print(colored_text("✅ 새 터미널에서 exec 세션이 시작되었습니다.", Colors.SUCCESS))
                time.sleep(1)
