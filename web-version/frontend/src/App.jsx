import React, { useState, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Layout, Menu, message, Spin } from 'antd';
import {
  DesktopOutlined,
  DatabaseOutlined,
  ThunderboltOutlined,
  ContainerOutlined,
  SettingOutlined,
  CloudServerOutlined,
} from '@ant-design/icons';
import { useQuery } from 'react-query';

// 페이지 컴포넌트들
import ProfileSelector from './components/ProfileSelector';
import RegionSelector from './components/RegionSelector';
import EC2Dashboard from './pages/EC2Dashboard';
import RDSDashboard from './pages/RDSDashboard';
import ECSDashboard from './pages/ECSDashboard';
import CacheDashboard from './pages/CacheDashboard';
import SystemStatus from './pages/SystemStatus';

// API 서비스
import { profilesApi } from './services/api';

const { Header, Sider, Content } = Layout;

function App() {
  const [collapsed, setCollapsed] = useState(false);
  const [selectedProfile, setSelectedProfile] = useState(null);
  const [selectedRegion, setSelectedRegion] = useState(null);
  const [currentPage, setCurrentPage] = useState('ec2');

  // 프로파일 목록 조회
  const { data: profilesData, isLoading: profilesLoading, error: profilesError } = useQuery(
    'profiles',
    () => profilesApi.list(),
    {
      onSuccess: (response) => {
        const profiles = response.data;
        if (profiles.profiles && profiles.profiles.length > 0) {
          setSelectedProfile(profiles.default_profile || profiles.profiles[0]);
        }
      },
      onError: (error) => {
        message.error('프로파일을 불러오는데 실패했습니다: ' + error.message);
      }
    }
  );

  // 리전 목록 조회
  const { data: regionsData, isLoading: regionsLoading } = useQuery(
    ['regions', selectedProfile],
    () => selectedProfile ? profilesApi.getRegions(selectedProfile) : null,
    {
      enabled: !!selectedProfile,
      onSuccess: (response) => {
        const regions = response.data.regions;
        if (regions && regions.length > 0 && !selectedRegion) {
          setSelectedRegion('multi-region'); // 기본적으로 멀티 리전 선택
        }
      }
    }
  );

  const menuItems = [
    {
      key: 'ec2',
      icon: <DesktopOutlined />,
      label: 'EC2 인스턴스',
    },
    {
      key: 'rds',
      icon: <DatabaseOutlined />,
      label: 'RDS 데이터베이스',
    },
    {
      key: 'ecs',
      icon: <ContainerOutlined />,
      label: 'ECS 컨테이너',
    },
    {
      key: 'cache',
      icon: <ThunderboltOutlined />,
      label: 'ElastiCache',
    },
    {
      key: 'system',
      icon: <SettingOutlined />,
      label: '시스템 상태',
    },
  ];

  const renderContent = () => {
    if (!selectedProfile || !selectedRegion) {
      return (
        <div style={{ textAlign: 'center', padding: '50px' }}>
          <CloudServerOutlined style={{ fontSize: '64px', color: '#1890ff', marginBottom: '16px' }} />
          <h2>EC2Menu Web</h2>
          <p>AWS 프로파일과 리전을 선택해주세요.</p>
        </div>
      );
    }

    switch (currentPage) {
      case 'ec2':
        return <EC2Dashboard profile={selectedProfile} region={selectedRegion} />;
      case 'rds':
        return <RDSDashboard profile={selectedProfile} region={selectedRegion} />;
      case 'ecs':
        return <ECSDashboard profile={selectedProfile} region={selectedRegion} />;
      case 'cache':
        return <CacheDashboard profile={selectedProfile} region={selectedRegion} />;
      case 'system':
        return <SystemStatus />;
      default:
        return <EC2Dashboard profile={selectedProfile} region={selectedRegion} />;
    }
  };

  if (profilesLoading) {
    return (
      <div className="loading-overlay">
        <Spin size="large" />
        <div style={{ marginLeft: '16px' }}>프로파일을 불러오는 중...</div>
      </div>
    );
  }

  if (profilesError) {
    return (
      <div style={{ textAlign: 'center', padding: '50px' }}>
        <h2>오류가 발생했습니다</h2>
        <p>AWS 프로파일을 불러올 수 없습니다. 백엔드 서버가 실행 중인지 확인해주세요.</p>
      </div>
    );
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}>
        <div style={{ 
          height: 32, 
          margin: 16, 
          background: 'rgba(255, 255, 255, 0.3)',
          borderRadius: 6,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'white',
          fontWeight: 'bold'
        }}>
          {collapsed ? 'EC2' : 'EC2Menu'}
        </div>
        <Menu
          theme="dark"
          defaultSelectedKeys={['ec2']}
          selectedKeys={[currentPage]}
          mode="inline"
          items={menuItems}
          onClick={({ key }) => setCurrentPage(key)}
        />
      </Sider>
      
      <Layout>
        <Header style={{ 
          background: '#fff', 
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
        }}>
          <h1 style={{ margin: 0, color: '#1890ff' }}>
            AWS 리소스 관리 대시보드
          </h1>
          
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
            <ProfileSelector
              profiles={profilesData?.data?.profiles || []}
              selectedProfile={selectedProfile}
              onSelect={setSelectedProfile}
              loading={profilesLoading}
            />
            
            <RegionSelector
              regions={regionsData?.data?.regions || []}
              selectedRegion={selectedRegion}
              onSelect={setSelectedRegion}
              loading={regionsLoading}
              disabled={!selectedProfile}
            />
          </div>
        </Header>
        
        <Content style={{ margin: '16px' }}>
          <div style={{ 
            padding: 24, 
            minHeight: 360, 
            background: '#fff',
            borderRadius: 8,
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
          }}>
            {renderContent()}
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}

export default App;