import React from 'react';
import { Card, Empty } from 'antd';
import { DatabaseOutlined } from '@ant-design/icons';

function RDSDashboard({ profile, region }) {
  return (
    <Card>
      <Empty
        image={<DatabaseOutlined style={{ fontSize: '64px', color: '#1890ff' }} />}
        description={
          <div>
            <h3>RDS 대시보드</h3>
            <p>RDS 데이터베이스 관리 기능을 구현 중입니다.</p>
            <p>현재 선택된 프로파일: <strong>{profile}</strong></p>
            <p>현재 선택된 리전: <strong>{region}</strong></p>
          </div>
        }
      />
    </Card>
  );
}

export default RDSDashboard;