'use strict';
const $ = id => document.getElementById(id);
let state = null, current = Number(localStorage.getItem('care-patient')) || 1, posting = false, lastView = '', lastChat = '';
const drafts = {}, requestIds = {};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusText = {pending:'待处理',possible:'可能完成，等你确认',completed:'已完成',cancelled:'已取消'};
const ownerText = {caregiver:'照护师',patient:'患者'};
const stageText = {analyze_user:'待办助手正在检查你的消息',reply:'模拟患者正在回复',analyze_patient:'待办助手正在检查患者回复'};
const actionText = {confirm:'确认完成',reject:'还没完成',reopen:'重新打开',cancel:'取消事项',edit:'手动修改',assistant:'助手更新'};
const time = value => new Date(value).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
function showError(error) { $('error').textContent = error?.message || String(error); $('error').hidden = false; }
function clearError() { $('error').hidden = true; }
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':state?.csrf || ''},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败');
  return result;
}
async function refresh() {
  state = await api('/api/state');
  if (!state.patients.some(p => p.id === current)) current = 1;
  render();
}
function busy(patientId) { return state.jobs.some(j => j.patient_id === patientId && ['queued','running'].includes(j.status)); }
function render() {
  const key = JSON.stringify([state.patients,state.tasks,state.jobs,current,$('scope').value,$('status').value]);
  if (key !== lastView) {
    lastView = key;
    $('patients').innerHTML = state.patients.map(p => `<button class="patient ${p.id===current?'active':''}" data-patient="${p.id}" aria-pressed="${p.id===current}"><span class="avatar">${esc(p.name[0])}</span><span><strong>${esc(p.name)}</strong><small>${esc(p.label)} · ${state.tasks.filter(t=>t.patient_id===p.id && ['pending','possible'].includes(t.status)).length} 项待跟进</small></span></button>`).join('');
    const patient = state.patients.find(p => p.id === current);
    $('patient-name').textContent = patient.name;
    $('patient-intro').textContent = patient.intro;
    renderTasks();
  }
  const messages = state.messages.filter(m=>m.patient_id===current);
  const chatKey = JSON.stringify([current,messages]);
  if (chatKey !== lastChat) {
    lastChat = chatKey;
    $('messages').innerHTML = messages.length ? messages.map(m=>`<article class="message ${m.role}"><div class="meta">${m.role==='caregiver'?'你 · 照护师':esc(state.patients.find(p=>p.id===current).name)} · ${time(m.created_at)}</div><div class="bubble">${esc(m.content)}</div></article>`).join('') : '<div class="empty"><div class="symbol">◌</div><strong>从一个约定开始</strong><br>发送第一条消息，或让患者主动提问。<br>待办助手会自动在旁整理需要跟进的事。</div>';
    $('messages').scrollTop = $('messages').scrollHeight;
  }
  const job = state.jobs.find(j=>j.patient_id===current);
  const jobKey = JSON.stringify(job);
  if ($('job').dataset.key !== jobKey) {
    $('job').dataset.key = jobKey;
    $('job').className = 'job' + (job?.status==='failed'?' failed':'');
    $('job').innerHTML = !job ? '' : job.status==='failed' ? `<strong>处理未完成 · ${esc(stageText[job.stage])}</strong><br>${esc(job.error)}<br><button data-retry="${esc(job.id)}">重试失败步骤</button>` : `◌ 正在处理 · ${job.status==='queued'?'等待本机模型':esc(stageText[job.stage])}…`;
  }
  $('send').disabled = posting || !!job;
  $('proactive').disabled = posting || !!job;
  $('message').disabled = posting;
  $('reset').disabled = state.jobs.some(j=>['queued','running'].includes(j.status));
}
function renderTasks() {
  const filtered = state.tasks.filter(t=>($('scope').value==='all'||t.patient_id===current) && ($('status').value==='all'||($('status').value==='active'?(['pending','possible'].includes(t.status)||t.signal==='contradiction'):t.status===$('status').value)));
  $('task-count').textContent = filtered.length;
  $('tasks').innerHTML = ['caregiver','patient'].map(owner => {
    const tasks = filtered.filter(t=>t.owner===owner);
    return `<div class="group-title">${owner==='caregiver'?'照护师待办':'患者自己的待办'} · ${tasks.length}</div>` + (tasks.length ? tasks.map(t => {
      const patient = state.patients.find(p=>p.id===t.patient_id);
      const disabled = busy(t.patient_id)?' disabled':'';
      const note = t.signal==='contradiction'?'后续说法有矛盾，请核实':t.signal==='partial'?'部分完成，仍有剩余事项':t.signal==='uncertain'?'不确定，需要核实':t.status==='possible'?'发现完成线索，请查看原话后确认':'';
      const action = (a,label,cls='')=>`<button data-action="${a}" data-id="${t.id}" class="${cls}"${disabled}>${label}</button>`;
      const actions = ['completed','cancelled'].includes(t.status) ? action('reopen','重新打开') : action('confirm','确认完成','confirm')+(t.status==='possible'||['uncertain','contradiction'].includes(t.signal)?action('reject','还没完成'):'')+action('cancel','取消事项');
      return `<article class="task"><div class="task-top"><span>${esc(patient.name)} · ${ownerText[t.owner]}</span><span class="status ${t.signal==='contradiction'?'contradiction':t.status}">${statusText[t.status]}</span></div><button class="task-title" data-detail="${t.id}">${esc(t.title)}</button><div class="task-due">约定时间：${esc(t.due || '未约定')}</div>${note?`<div class="task-note">${note}${t.remaining?`<br>剩余：${esc(t.remaining)}`:''}</div>`:''}<div class="task-actions">${actions}${action('edit','修改')}<button data-detail="${t.id}">查看依据 ${t.evidence.length}</button></div></article>`;
    }).join('') : '<div class="muted">暂无事项。新的请求和承诺会自动出现在这里。</div>');
  }).join('');
}
async function checkHealth() {
  $('check').disabled = true;
  $('health').textContent = '正在检查 Ollama 和本机模型…';
  try { const health = await api('/api/health'); $('health').textContent = (health.ok?'● ':'⚠ ') + health.message; }
  catch(error) { $('health').textContent = '无法连接小程序，请检查运行程序的终端。'; }
  finally { $('check').disabled = false; }
}
async function send(proactive = false) {
  if (posting || !state) return;
  const patientId = current, content = $('message').value.trim();
  if (!proactive && !content) return;
  const fingerprint = JSON.stringify([patientId,content,proactive]);
  const requestId = requestIds[fingerprint] ||= crypto.randomUUID();
  posting = true; clearError(); render();
  try {
    await api('/api/send', {patient_id:patientId, content, proactive, request_id:requestId});
    delete requestIds[fingerprint];
    if (!proactive) { drafts[patientId]=''; if (current===patientId) $('message').value=''; }
    await refresh();
  } catch(error) { showError(error); }
  finally { posting=false; render(); }
}
function showDetail(id) {
  const task=state.tasks.find(t=>t.id===id);
  $('detail-content').innerHTML = `<h3>${esc(task.title)}</h3><p>${ownerText[task.owner]} · ${statusText[task.status]} · ${esc(task.due || '未约定时间')}</p>${task.reason?`<p>${esc(task.reason)}</p>`:''}${task.remaining?`<p>剩余事项：${esc(task.remaining)}</p>`:''}<div class="detail-label">来自以下对话 · 句子编号用于追溯</div>` + task.evidence.map(mid=>{
    const m=state.messages.find(m=>m.id===mid);
    return m ? `<blockquote class="evidence"><small>#${m.id} · ${ownerText[m.role]} · ${time(m.created_at)}${task.suggestion.includes(mid)?' · 本次判断依据':''}${task.dismissed.includes(mid)?' · 已处理此依据':''}</small>${esc(m.content)}</blockquote>` : '';
  }).join('') + '<div class="detail-label">操作记录</div><div class="history">' + state.audit.filter(a=>a.task_id===id).map(a=>`${time(a.created_at)} · ${actionText[a.action] || esc(a.action)}`).join('<br>') + '</div>';
  $('detail').showModal();
}
$('patients').addEventListener('click', event=>{
  const button=event.target.closest('[data-patient]'); if (!button || posting) return;
  drafts[current]=$('message').value; current=Number(button.dataset.patient); localStorage.setItem('care-patient',current);
  $('message').value=drafts[current] || ''; render();
});
$('tasks').addEventListener('click', async event=>{
  const detail=event.target.closest('[data-detail]'); if (detail) { showDetail(Number(detail.dataset.detail)); return; }
  const button=event.target.closest('[data-action]'); if (!button || button.disabled) return;
  const id=Number(button.dataset.id), action=button.dataset.action;
  if (action==='edit') {
    const task=state.tasks.find(t=>t.id===id);
    $('edit-id').value=id; $('edit-title').value=task.title; $('edit-owner').value=task.owner; $('edit-due').value=task.due; $('edit').showModal(); return;
  }
  button.disabled=true; clearError();
  try { await api('/api/task',{id,action}); await refresh(); } catch(error) { showError(error); button.disabled=false; }
});
$('job').addEventListener('click',async event=>{
  const button=event.target.closest('[data-retry]'); if (!button) return;
  button.disabled=true; clearError();
  try { await api('/api/retry',{job_id:button.dataset.retry}); await refresh(); } catch(error) { showError(error); button.disabled=false; }
});
$('edit-form').addEventListener('submit',async event=>{
  event.preventDefault(); clearError();
  try { await api('/api/task',{id:Number($('edit-id').value),action:'edit',title:$('edit-title').value,owner:$('edit-owner').value,due:$('edit-due').value}); $('edit').close(); await refresh(); } catch(error) { showError(error); }
});
$('chat-form').addEventListener('submit',event=>{event.preventDefault();send();});
$('message').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();send();}});
$('proactive').addEventListener('click',()=>send(true));
$('scope').addEventListener('change',render); $('status').addEventListener('change',render);
$('close-detail').addEventListener('click',()=>$('detail').close());
$('cancel-edit').addEventListener('click',()=>$('edit').close());
$('check').addEventListener('click',checkHealth);
$('reset').addEventListener('click',()=>$('reset-dialog').showModal());
$('cancel-reset').addEventListener('click',()=>$('reset-dialog').close());
$('confirm-reset').addEventListener('click',async()=>{
  $('confirm-reset').disabled=true; clearError();
  try { await api('/api/reset',{confirmation:'重新开始'}); $('reset-dialog').close(); Object.keys(drafts).forEach(k=>delete drafts[k]); $('message').value=''; await refresh(); }
  catch(error) { showError(error); } finally { $('confirm-reset').disabled=false; }
});
async function poll() { try { await refresh(); } catch(error) { showError(new Error('小程序连接中断，请检查终端是否仍在运行。已保存的数据仍在本地。')); } finally { setTimeout(poll,1500); } }
poll(); checkHealth();
