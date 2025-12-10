import axios from 'axios';

// API 클라이언트 설정
const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

// 요청 인터셉터
api.interceptors.request.use(
  (config) => {
    // 로딩 상태 표시 등의 로직
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 응답 인터셉터
api.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    // 에러 처리
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

// ============================================================================
// 프로파일 및 리전 관련 API
// ============================================================================

export const profilesApi = {
  list: () => api.get('/profiles'),
  getRegions: (profile) => api.get(`/profiles/${profile}/regions`),
};

// ============================================================================
// EC2 관련 API
// ============================================================================

export const ec2Api = {
  listInstances: (profile, region, forceRefresh = false) =>
    api.get(`/profiles/${profile}/regions/${region}/instances`, {
      params: { force_refresh: forceRefresh }
    }),
  
  listJumpHosts: (profile, region) =>
    api.get(`/profiles/${profile}/regions/${region}/jump-hosts`),
  
  startTerminalSession: (profile, region, instanceId) =>
    api.post(`/profiles/${profile}/regions/${region}/instances/${instanceId}/terminal`),
  
  terminateTerminalSession: (sessionId) =>
    api.delete(`/terminal/sessions/${sessionId}`),
  
  startRdpTunnel: (profile, region, instanceId) =>
    api.post(`/profiles/${profile}/regions/${region}/instances/${instanceId}/rdp`),

  startWebRdp: (profile, region, instanceId) =>
    api.post(`/profiles/${profile}/regions/${region}/instances/${instanceId}/rdp-web`),
};

// ============================================================================
// RDS 관련 API
// ============================================================================

export const rdsApi = {
  listInstances: (profile, region, forceRefresh = false) =>
    api.get(`/profiles/${profile}/regions/${region}/rds`, {
      params: { force_refresh: forceRefresh }
    }),
  
  startTunnel: (profile, region, dbInstanceId, tunnelRequest) =>
    api.post(`/profiles/${profile}/regions/${region}/rds/${dbInstanceId}/tunnel`, tunnelRequest),
};

// ============================================================================
// ECS 관련 API
// ============================================================================

export const ecsApi = {
  listClusters: (profile, region, forceRefresh = false) =>
    api.get(`/profiles/${profile}/regions/${region}/ecs/clusters`, {
      params: { force_refresh: forceRefresh }
    }),
  
  listTasks: (profile, region, clusterName, serviceName = null, forceRefresh = false) =>
    api.get(`/profiles/${profile}/regions/${region}/ecs/clusters/${clusterName}/tasks`, {
      params: { service_name: serviceName, force_refresh: forceRefresh }
    }),
};

// ============================================================================
// ElastiCache 관련 API
// ============================================================================

export const cacheApi = {
  listClusters: (profile, region, forceRefresh = false) =>
    api.get(`/profiles/${profile}/regions/${region}/cache`, {
      params: { force_refresh: forceRefresh }
    }),
};

// ============================================================================
// 파일 전송 관련 API
// ============================================================================

export const fileApi = {
  upload: (profile, file, onProgress) => {
    const formData = new FormData();
    formData.append('file', file);
    
    return api.post(`/profiles/${profile}/files/upload`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: onProgress,
    });
  },
  
  transferToInstances: (profile, transferRequest) =>
    api.post(`/profiles/${profile}/files/transfer`, transferRequest),
  
  getBatchJobStatus: (jobId, profile) =>
    api.get(`/batch-jobs/${jobId}`, { params: { profile } }),
};

// ============================================================================
// 터널 관련 API
// ============================================================================

export const tunnelApi = {
  terminate: (tunnelId) => api.delete(`/tunnels/${tunnelId}`),
};

// ============================================================================
// 시스템 관련 API
// ============================================================================

export const systemApi = {
  getStatus: () => api.get('/status'),
  listActiveSessions: () => api.get('/sessions'),
};

export default api;