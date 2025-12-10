import React from 'react';
import { Card, Row, Col, Statistic, Table, Tag } from 'antd';
import { 
  DesktopOutlined, 
  DatabaseOutlined, 
  CloudServerOutlined,
  TeamOutlined 
} from '@ant-design/icons';
import { useQuery } from 'react-query';
import { systemApi } from '../services/api';

function SystemStatus() {
  // 시스템 상태 조회
  const { data: statusData, isLoading: statusLoading } = useQuery(
    'system-status',
    () => systemApi.getStatus(),
    {
      refetchInterval: 5000, // 5초마다 새로고침
    }
  );

  // 활성 세션 목록 조회
  const { data: sessionsData, isLoading: sessionsLoading } = useQuery(
    'active-sessions',
    () => systemApi.listActiveSessions(),
    {
      refetchInterval: 10000, // 10초마다 새로고침
    }
  );

  const status = statusData?.data || {};
  const sessions = sessionsData?.data || {};

  // 터미널 세션 테이블 컬럼
  const terminalColumns = [
    {
      title: '세션 ID',
      dataIndex: 'session_id',
      key: 'session_id',
      render: (id) => <code>{id.substring(0, 8)}...</code>,
    },
    {
      title: '인스턴스 ID',
      dataIndex: 'instance_id',
      key: 'instance_id',
    },
    {
      title: '프로파일',
      dataIndex: 'profile',
      key: 'profile',
      render: (profile) => <Tag color="blue">{profile}</Tag>,
    },
    {
      title: '리전',
      dataIndex: 'region',
      key: 'region',
      render: (region) => <Tag color="green">{region}</Tag>,
    },
    {
      title: '상태',
      dataIndex: 'status',
      key: 'status',
      render: (status) => (
        <Tag color={status === 'active' ? 'green' : 'red'}>
          {status.toUpperCase()}
        </Tag>
      ),
    },
  ];

  // 터널 세션 테이블 컬럼
  const tunnelColumns = [
    {
      title: '터널 ID',
      dataIndex: 'tunnel_id',
      key: 'tunnel_id',
      render: (id) => <code>{id.substring(0, 8)}...</code>,
    },
    {
      title: '타입',
      key: 'type',
      render: (_, record) => (
        <Tag color="purple">
          {record.db_endpoint ? 'RDS' : 'RDP'}
        </Tag>
      ),
    },
    {
      title: '대상',
      key: 'target',
      render: (_, record) => (
        record.db_endpoint || record.instance_id
      ),
    },
    {
      title: '로컬 포트',
      dataIndex: 'local_port',
      key: 'local_port',
      render: (port) => <code>localhost:{port}</code>,
    },
    {
      title: '프로파일',
      dataIndex: 'profile',
      key: 'profile',
      render: (profile) => <Tag color="blue">{profile}</Tag>,
    },
    {
      title: '상태',
      dataIndex: 'status',
      key: 'status',
      render: (status) => (
        <Tag color={status === 'active' ? 'green' : 'red'}>
          {status.toUpperCase()}
        </Tag>
      ),
    },
  ];

  const terminalSessions = Object.values(sessions.terminal_sessions || {});
  const tunnels = Object.values(sessions.tunnels || {});

  return (
    <div>
      {/* 시스템 통계 */}
      <Row gutter={16} style={{ marginBottom: '24px' }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="시스템 상태"
              value={status.status === 'healthy' ? '정상' : '오류'}
              valueStyle={{ 
                color: status.status === 'healthy' ? '#3f8600' : '#cf1322' 
              }}
              prefix={<CloudServerOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="활성 터미널 세션"
              value={status.active_sessions || 0}
              prefix={<DesktopOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="활성 터널"
              value={status.active_tunnels || 0}
              prefix={<DatabaseOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="캐시된 매니저"
              value={status.cached_managers || 0}
              prefix={<TeamOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 활성 터미널 세션 */}
      <Card 
        title="🖥️ 활성 터미널 세션" 
        style={{ marginBottom: '24px' }}
      >
        <Table
          columns={terminalColumns}
          dataSource={terminalSessions}
          rowKey="session_id"
          loading={sessionsLoading}
          pagination={false}
          size="small"
          locale={{
            emptyText: '활성 터미널 세션이 없습니다'
          }}
        />
      </Card>

      {/* 활성 터널 */}
      <Card title="🔗 활성 포트 포워딩 터널">
        <Table
          columns={tunnelColumns}
          dataSource={tunnels}
          rowKey="tunnel_id"
          loading={sessionsLoading}
          pagination={false}
          size="small"
          locale={{
            emptyText: '활성 터널이 없습니다'
          }}
        />
      </Card>

      {/* 시스템 정보 */}
      <Card 
        title="📊 시스템 정보" 
        style={{ marginTop: '24px' }}
      >
        <Row gutter={16}>
          <Col span={12}>
            <div style={{ padding: '16px', background: '#f5f5f5', borderRadius: '8px' }}>
              <h4>백엔드 서버</h4>
              <p>상태: <Tag color="green">실행 중</Tag></p>
              <p>API 버전: 1.0.0</p>
              <p>포트: 8000</p>
            </div>
          </Col>
          <Col span={12}>
            <div style={{ padding: '16px', background: '#f5f5f5', borderRadius: '8px' }}>
              <h4>프론트엔드</h4>
              <p>상태: <Tag color="green">실행 중</Tag></p>
              <p>프레임워크: React 18</p>
              <p>포트: 3000</p>
            </div>
          </Col>
        </Row>
      </Card>
    </div>
  );
}

export default SystemStatus;