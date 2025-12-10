import React from 'react';
import { Card, Empty } from 'antd';
import { ContainerOutlined } from '@ant-design/icons';

function ECSDashboard({ profile, region }) {
  return (
    <Card>
      <Empty
        image={<ContainerOutlined style={{ fontSize: '64px', color: '#1890ff' }} />}
        description={
          <div>
            <h3>ECS 대시보드</h3>
            <p>ECS 컨테이너 관리 기능을 구현 중입니다.</p>
            <p>현재 선택된 프로파일: <strong>{profile}</strong></p>
            <p>현재 선택된 리전: <strong>{region}</strong></p>
          </div>
        }
      />
    </Card>
  );
}

export default ECSDashboard;