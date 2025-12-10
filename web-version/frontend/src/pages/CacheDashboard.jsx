import React from 'react';
import { Card, Empty } from 'antd';
import { ThunderboltOutlined } from '@ant-design/icons';

function CacheDashboard({ profile, region }) {
  return (
    <Card>
      <Empty
        image={<ThunderboltOutlined style={{ fontSize: '64px', color: '#1890ff' }} />}
        description={
          <div>
            <h3>ElastiCache 대시보드</h3>
            <p>ElastiCache 클러스터 관리 기능을 구현 중입니다.</p>
            <p>현재 선택된 프로파일: <strong>{profile}</strong></p>
            <p>현재 선택된 리전: <strong>{region}</strong></p>
          </div>
        }
      />
    </Card>
  );
}

export default CacheDashboard;