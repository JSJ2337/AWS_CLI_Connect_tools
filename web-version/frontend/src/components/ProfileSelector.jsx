import React from 'react';
import { Select, Spin } from 'antd';
import { UserOutlined } from '@ant-design/icons';

const { Option } = Select;

function ProfileSelector({ profiles, selectedProfile, onSelect, loading }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
      <UserOutlined style={{ color: '#1890ff' }} />
      <span style={{ color: '#666', minWidth: '60px' }}>프로파일:</span>
      <Select
        value={selectedProfile}
        onChange={onSelect}
        loading={loading}
        style={{ minWidth: '150px' }}
        placeholder="프로파일 선택"
        notFoundContent={loading ? <Spin size="small" /> : '프로파일이 없습니다'}
      >
        {profiles.map(profile => (
          <Option key={profile} value={profile}>
            {profile}
          </Option>
        ))}
      </Select>
    </div>
  );
}

export default ProfileSelector;