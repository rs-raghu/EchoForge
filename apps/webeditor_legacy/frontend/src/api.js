const API_BASE = import.meta.env.VITE_API_BASE || '';

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });

  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = { raw: text }; }
  }

  if (!res.ok) {
    const msg = data?.detail?.message || data?.detail || data?.raw || res.statusText;
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2));
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  base: API_BASE,
  health: () => request('/api/health'),
  listProjects: () => request('/api/projects'),
  bootstrapProject: (id, force = false) => request(`/api/projects/${encodeURIComponent(id)}/bootstrap?force=${force}`, { method: 'POST' }),
  getEditor: (id) => request(`/api/projects/${encodeURIComponent(id)}/editor`),
  saveEditor: (id, project) => request(`/api/projects/${encodeURIComponent(id)}/editor`, { method: 'POST', body: JSON.stringify({ project }) }),
  patchClip: (id, clipId, patch) => request(`/api/projects/${encodeURIComponent(id)}/clips/${encodeURIComponent(clipId)}`, { method: 'PATCH', body: JSON.stringify({ patch }) }),
  reloadLyrics: (id, keepStyle = true) => request(`/api/projects/${encodeURIComponent(id)}/reload-lyrics`, { method: 'POST', body: JSON.stringify({ keep_style: keepStyle }) }),
  
  startRender: (id, project) => request(`/api/projects/${encodeURIComponent(id)}/render/start`, { method: 'POST', body: JSON.stringify({ project }) }),
  
  // NATIVE SSE STREAMER
  streamJob: (jobId, onUpdate, onError) => {
    const es = new EventSource(`${API_BASE}/api/render-jobs/${encodeURIComponent(jobId)}/events`);
    es.onmessage = (e) => {
      const job = JSON.parse(e.data);
      onUpdate(job);
      // Close automatically when the job naturally finishes
      if (job.status === 'completed' || job.status === 'failed') es.close();
    };
    es.onerror = (err) => { onError(err); es.close(); };
    
    // Returning the instance allows main.jsx to manually close it if the component unmounts early
    return es;
  },

  scheduleUpload: (id, payload) => request(`/api/projects/${encodeURIComponent(id)}/upload/schedule`, { method: 'POST', body: JSON.stringify(payload) }),
  mediaUrl: (id, path) => `${API_BASE}/api/projects/${encodeURIComponent(id)}/media?path=${encodeURIComponent(path || '')}`,
  downloadUrl: (id, path) => `${API_BASE}/api/projects/${encodeURIComponent(id)}/download?path=${encodeURIComponent(path || '')}`,
};