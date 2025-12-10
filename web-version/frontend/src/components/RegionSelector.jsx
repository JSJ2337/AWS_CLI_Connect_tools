import React from 'react';
import { Select, Spin } from 'antd';
import { GlobalOutlined } from '@ant-design/icons';

const { Option } = Select;

function RegionSelector({ regions, selectedRegion, onSelect, loading, disabled }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
      <GlobalOutlined style={{ color: '#1890ff' }} />
      <span style={{ color: '#666', minWidth: '40px' }}>리전:</span>
      <Select
        value={selectedRegion}
        onChange={onSelect}
        loading={loading}
        disabled={disabled}
        style={{ minWidth: '180px' }}
        placeholder="리전 선택"
        notFoundContent={loading ? <Spin size="small" /> : '리전이 없습니다'}
      >
        <Option value="multi-region">
          🌍 All Regions (멀티 리전)
        </Option>
        {regions.map(region => (
          <Option key={region} value={region}>
            {region}
          </Option>
        ))}
      </Select>
    </div>
  );
}

export default RegionSelector;