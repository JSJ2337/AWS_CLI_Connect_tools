import React, { useState } from 'react';
import { 
  Table, 
  Button, 
  Tag, 
  Space, 
  message, 
  Modal, 
  Tooltip,
  Input,
  Card,
  Row,
  Col,
  Statistic
} from 'antd';
import {
  PlayCircleOutlined,
  DesktopOutlined,
  GlobalOutlined,
  ReloadOutlined,
  SearchOutlined,
  WindowsOutlined,
  AppleOutlined,
  LinuxOutlined
} from '@ant-design/icons';
import { useQuery, useMutation } from 'react-query';
import { ec2Api } from '../services/api';
import Terminal from '../components/Terminal';

function EC2Dashboard({ profile, region }) {
  const [searchText, setSearchText] = useState('');
  const [selectedInstance, setSelectedInstance] = useState(null);
  const [terminalVisible, setTerminalVisible] = useState(false);
  const [terminalSession, setTerminalSession] = useState(null);

  // EC2 인스턴스 목록 조회
  const { 
    data: instancesData, 
    isLoading, 
    refetch,
    error 
  } = useQuery(
    ['instances', profile, region],
    () => ec2Api.listInstances(profile, region),
    {
      enabled: !!(profile && region),
      onError: (error) => {
        message.error('인스턴스 목록 조회 실패: ' + error.message);
      }
    }
  );

  // 터미널 세션 시작 뮤테이션
  const startTerminalMutation = useMutation(
    ({ profile, region, instanceId }) => 
      ec2Api.startTerminalSession(profile, region, instanceId),
    {
      onSuccess: (response) => {
        setTerminalSession(response.data);
        setTerminalVisible(true);
        message.success('터미널 세션이 시작되었습니다');
      },
      onError: (error) => {
        message.error('터미널 세션 시작 실패: ' + error.message);
      }
    }
  );

  // 웹 RDP 시작 뮤테이션
  const startWebRdpMutation = useMutation(
    ({ profile, region, instanceId }) =>
      ec2Api.startWebRdp(profile, region, instanceId),
    {
      onSuccess: (response) => {
        const rdpInfo = response.data;

        // 새 탭에서 웹 RDP 열기
        const rdpWindow = window.open(rdpInfo.rdp_url, '_blank', 'width=1200,height=800');
        if (rdpWindow) {
          message.success('웹 RDP가 새 탭에서 열렸습니다.');
        } else {
          message.warning('팝업이 차단되었습니다. 브라우저 설정을 확인해주세요.');
        }
      },
      onError: (error) => {
        message.error('웹 RDP 연결 실패: ' + error.message);
      }
    }
  );

  // RDP 터널 시작 뮤테이션
  const startRdpMutation = useMutation(
    ({ profile, region, instanceId }) => 
      ec2Api.startRdpTunnel(profile, region, instanceId),
    {
      onSuccess: (response) => {
        const tunnelInfo = response.data;
        
        // RDP 연결 옵션 모달 표시
        Modal.info({
          title: '🖥️ RDP 연결 준비 완료',
          width: 600,
          content: (
            <div>
              <p>포트 포워딩이 설정되었습니다:</p>
              <div style={{ background: '#f5f5f5', padding: '12px', margin: '12px 0', borderRadius: '4px' }}>
                <strong>localhost:{tunnelInfo.local_port}</strong>
              </div>
              
              <div style={{ marginTop: '16px' }}>
                <h4>연결 방법을 선택하세요:</h4>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button
                    type="primary"
                    block
                    onClick={() => {
                      // EC2Menu 로컬 헬퍼를 통한 자동 RDP 연결
                      try {
                        const ec2rdpUrl = `ec2rdp://localhost:${tunnelInfo.local_port}`;
                        window.location.href = ec2rdpUrl;
                        message.success('RDP 클라이언트가 자동으로 실행됩니다.');
                      } catch (e) {
                        console.error('EC2RDP 프로토콜 연결 실패:', e);

                        // 대체 방법: .rdp 파일 다운로드
                        const blob = new Blob([tunnelInfo.rdp_file_content], { type: 'application/rdp' });
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `${selectedInstance.name || selectedInstance.instance_id}.rdp`;
                        a.click();
                        window.URL.revokeObjectURL(url);

                        message.warning('로컬 헬퍼를 사용할 수 없어 RDP 파일을 다운로드했습니다. 파일을 실행하여 접속하세요.');
                      }
                    }}
                  >
                    🚀 mstsc 실행
                  </Button>
                  
                  <Button 
                    block
                    onClick={() => {
                      navigator.clipboard.writeText(`localhost:${tunnelInfo.local_port}`);
                      message.success('연결 정보가 클립보드에 복사되었습니다');
                    }}
                  >
                    📋 연결 주소 복사
                  </Button>
                </Space>
              </div>
              
              <div style={{ marginTop: '16px', padding: '8px', background: '#fff7e6', borderRadius: '4px' }}>
                <small>
                  💡 팁: Windows 원격 데스크톱 연결(mstsc)을 열고 위 주소로 연결하세요.
                </small>
              </div>
            </div>
          ),
        });
      },
      onError: (error) => {
        message.error('RDP 터널 시작 실패: ' + error.message);
      }
    }
  );

  const handleTerminalConnect = (instance) => {
    setSelectedInstance(instance);
    startTerminalMutation.mutate({
      profile,
      region,
      instanceId: instance.instance_id
    });
  };

  const handleRdpConnect = (instance) => {
    setSelectedInstance(instance);
    startRdpMutation.mutate({
      profile,
      region,
      instanceId: instance.instance_id
    });
  };

  const handleWebRdpConnect = (instance) => {
    setSelectedInstance(instance);
    startWebRdpMutation.mutate({
      profile,
      region,
      instanceId: instance.instance_id
    });
  };

  const getStatusColor = (state) => {
    const colors = {
      'running': 'green',
      'stopped': 'red',
      'pending': 'orange',
      'stopping': 'orange',
      'starting': 'blue'
    };
    return colors[state] || 'default';
  };

  const getPlatformIcon = (platform) => {
    if (platform === 'windows') return <WindowsOutlined style={{ color: '#00a1f1' }} />;
    if (platform === 'macos') return <AppleOutlined style={{ color: '#000' }} />;
    return <LinuxOutlined style={{ color: '#ffa500' }} />;
  };

  const columns = [
    {
      title: '플랫폼',
      dataIndex: 'platform',
      key: 'platform',
      width: 60,
      render: (platform) => getPlatformIcon(platform),
    },
    {
      title: '이름',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <div>
          <div style={{ fontWeight: 'bold' }}>
            {name || '이름 없음'}
          </div>
          <div style={{ fontSize: '12px', color: '#666' }}>
            {record.instance_id}
          </div>
        </div>
      ),
      filteredValue: searchText ? [searchText] : null,
      onFilter: (value, record) => {
        const searchValue = value.toLowerCase();
        return (
          (record.name && record.name.toLowerCase().includes(searchValue)) ||
          record.instance_id.toLowerCase().includes(searchValue) ||
          record.instance_type.toLowerCase().includes(searchValue)
        );
      },
    },
    {
      title: '타입',
      dataIndex: 'instance_type',
      key: 'instance_type',
      width: 120,
    },
    {
      title: '상태',
      dataIndex: 'state',
      key: 'state',
      width: 100,
      render: (state) => (
        <Tag color={getStatusColor(state)}>
          {state.toUpperCase()}
        </Tag>
      ),
    },
    {
      title: 'IP 주소',
      key: 'ip',
      width: 150,
      render: (_, record) => (
        <div>
          {record.public_ip && (
            <div style={{ fontSize: '12px' }}>
              🌐 {record.public_ip}
            </div>
          )}
          {record.private_ip && (
            <div style={{ fontSize: '12px', color: '#666' }}>
              🏠 {record.private_ip}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '리전',
      dataIndex: 'region',
      key: 'region',
      width: 120,
      render: (region) => region && <Tag>{region}</Tag>,
    },
    {
      title: '작업',
      key: 'actions',
      width: 200,
      render: (_, record) => (
        <Space>
          <Tooltip title="SSH/SSM 터미널 접속">
            <Button
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleTerminalConnect(record)}
              disabled={record.state !== 'running'}
              loading={startTerminalMutation.isLoading && selectedInstance?.instance_id === record.instance_id}
            >
              터미널
            </Button>
          </Tooltip>
          
          {record.platform === 'windows' && (
            <>
              <Tooltip title="웹 브라우저에서 RDP 접속">
                <Button
                  size="small"
                  icon={<GlobalOutlined />}
                  onClick={() => handleWebRdpConnect(record)}
                  disabled={record.state !== 'running'}
                  loading={startWebRdpMutation.isLoading && selectedInstance?.instance_id === record.instance_id}
                  type="primary"
                >
                  웹 RDP
                </Button>
              </Tooltip>

              <Tooltip title="로컬 RDP 클라이언트 다운로드">
                <Button
                  size="small"
                  icon={<DesktopOutlined />}
                  onClick={() => handleRdpConnect(record)}
                  disabled={record.state !== 'running'}
                  loading={startRdpMutation.isLoading && selectedInstance?.instance_id === record.instance_id}
                >
                  RDP 다운로드
                </Button>
              </Tooltip>
            </>
          )}
        </Space>
      ),
    },
  ];

  const instances = instancesData?.data?.instances || [];
  
  // 통계 계산
  const stats = {
    total: instances.length,
    running: instances.filter(i => i.state === 'running').length,
    stopped: instances.filter(i => i.state === 'stopped').length,
    windows: instances.filter(i => i.platform === 'windows').length,
    linux: instances.filter(i => i.platform !== 'windows').length,
  };

  return (
    <div>
      {/* 통계 카드 */}
      <Row gutter={16} style={{ marginBottom: '24px' }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="전체 인스턴스"
              value={stats.total}
              prefix={<DesktopOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="실행 중"
              value={stats.running}
              valueStyle={{ color: '#3f8600' }}
              prefix={<PlayCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Windows"
              value={stats.windows}
              prefix={<WindowsOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Linux/Mac"
              value={stats.linux}
              prefix={<LinuxOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 검색 및 새로고침 */}
      <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between' }}>
        <Input
          placeholder="인스턴스 이름, ID, 타입으로 검색..."
          prefix={<SearchOutlined />}
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          style={{ width: 300 }}
          allowClear
        />
        
        <Button
          icon={<ReloadOutlined />}
          onClick={() => refetch()}
          loading={isLoading}
        >
          새로고침
        </Button>
      </div>

      {/* 인스턴스 테이블 */}
      <Table
        columns={columns}
        dataSource={instances}
        rowKey="instance_id"
        loading={isLoading}
        pagination={{
          pageSize: 20,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (total) => `총 ${total}개 인스턴스`,
        }}
        scroll={{ x: 1000 }}
      />

      {/* 터미널 모달 */}
      <Modal
        title={`🖥️ ${selectedInstance?.name || selectedInstance?.instance_id} - 터미널`}
        open={terminalVisible}
        onCancel={() => setTerminalVisible(false)}
        footer={null}
        width={900}
        destroyOnClose
      >
        {terminalSession && (
          <Terminal
            sessionId={terminalSession.session_id}
            websocketUrl={terminalSession.websocket_url}
          />
        )}
      </Modal>
    </div>
  );
}

export default EC2Dashboard;