const canvas = wx.createCanvas();
const ctx = canvas.getContext('2d');
const sys = wx.getSystemInfoSync();
const W = sys.windowWidth;
const H = sys.windowHeight;
const dpr = sys.pixelRatio || 1;
canvas.width = W * dpr;
canvas.height = H * dpr;
ctx.scale(dpr, dpr);

const STORE = 'draw-together-settings';
const state = {
  page: 'login', mode: 'login', username: '', password: '', endpoint: '', socketAuthType: 'join', token: '', roomCode: '',
  socket: null, connected: false, authenticated: false, reconnects: 0, reconnectTimer: null, hidden: false,
  players: [], strokes: [], role: 'guesser', clientId: '', color: '#ff6b57', round: null,
  word: '', messages: [], notice: '请输入账号登录', touch: null, gameOver: false
};
const saved = wx.getStorageSync(STORE) || {};
state.endpoint = saved.endpoint || 'ws://localhost:8765/ws';
state.username = saved.username || '';

function saveSettings() { wx.setStorageSync(STORE, { endpoint: state.endpoint, username: state.username }); }
function loginWithWechat() {
  if (!state.endpoint) { setNotice('请先配置服务器地址'); return; }
  const origin = state.endpoint.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:').replace(/\/ws(?:\?.*)?$/, '');
  wx.login({
    success(result) {
      if (!result.code) { setNotice('微信登录未取得临时凭证'); return; }
      wx.request({
        url: origin + '/_wechat_login?code=' + encodeURIComponent(result.code),
        method: 'GET',
        success(response) {
          const token = response.data && response.data.token;
          if (response.statusCode !== 200 || !token) {
            setNotice((response.data && response.data.error) || '微信登录暂不可用');
            return;
          }
          state.token = token;
          state.socketAuthType = 'session_token';
          state.mode = 'login';
          connect();
        },
        fail() { setNotice('无法连接微信登录服务'); }
      });
    },
    fail() { setNotice('微信登录失败'); }
  });
}
function text(value, fallback) { return typeof value === 'string' && value ? value : fallback; }
function setNotice(message) { state.notice = text(message, ''); draw(); }
function send(payload) {
  if (!state.socket || !state.connected) { setNotice('尚未连接服务器'); return false; }
  state.socket.send({ data: JSON.stringify(payload) });
  return true;
}
function addMessage(message, system) {
  state.messages.push({ text: message, system: !!system });
  if (state.messages.length > 7) state.messages.shift();
}
function openInput(title, value, callback) {
  wx.showModal({ title, editable: true, placeholderText: '请输入内容', content: value || '', success(result) {
    if (result.confirm) callback(result.content || '');
  } });
}
let hitAreas = [];
function button(x, y, w, h, label, action, accent) {
  ctx.fillStyle = accent ? '#ff6b57' : '#ffffff'; ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = '#17212b'; ctx.lineWidth = 2; ctx.strokeRect(x, y, w, h);
  ctx.fillStyle = accent ? '#ffffff' : '#17212b'; ctx.font = 'bold 15px sans-serif';
  ctx.textAlign = 'center'; ctx.fillText(label, x + w / 2, y + h / 2 + 5);
  return { x, y, w, h, action };
}
function layout() { hitAreas = []; }
function hit(x, y) {
  for (let i = hitAreas.length - 1; i >= 0; i -= 1) {
    const a = hitAreas[i];
    if (x >= a.x && x <= a.x + a.w && y >= a.y && y <= a.y + a.h) return a.action;
  }
  return null;
}
function header(title, subtitle) {
  ctx.fillStyle = '#17212b'; ctx.fillRect(0, 0, W, 74);
  ctx.fillStyle = '#ffffff'; ctx.textAlign = 'left'; ctx.font = 'bold 24px sans-serif'; ctx.fillText(title, 22, 35);
  ctx.font = '12px sans-serif'; ctx.fillStyle = '#b7c4cc'; ctx.fillText(subtitle, 23, 57);
}
function draw() {
  ctx.clearRect(0, 0, W, H); ctx.fillStyle = '#f4f0e8'; ctx.fillRect(0, 0, W, H); layout();
  if (state.page === 'login') drawLogin(); else if (state.page === 'lobby') drawLobby(); else drawRoom();
}
function drawLogin() {
  ctx.fillStyle = '#17212b'; ctx.fillRect(0, 0, W, 150);
  ctx.fillStyle = '#ffffff'; ctx.textAlign = 'left'; ctx.font = 'bold 31px sans-serif'; ctx.fillText('一起画', 24, 56);
  ctx.font = '14px sans-serif'; ctx.fillStyle = '#b7c4cc'; ctx.fillText('多人实时画板 · 猜词派对', 26, 84);
  ctx.fillStyle = '#17212b'; ctx.font = 'bold 18px sans-serif'; ctx.fillText(state.mode === 'login' ? '登录' : '注册新用户', 24, 192);
  ctx.font = '14px sans-serif'; ctx.fillStyle = '#53616b'; ctx.fillText('用户名', 24, 233); ctx.fillText(state.username || '点击输入用户名', 24, 258);
  ctx.strokeStyle = '#9aa5aa'; ctx.beginPath(); ctx.moveTo(24, 268); ctx.lineTo(W - 24, 268); ctx.stroke();
  ctx.fillText('密码', 24, 308); ctx.fillText(state.password ? '••••••••' : '点击输入密码', 24, 333);
  ctx.strokeStyle = '#9aa5aa'; ctx.beginPath(); ctx.moveTo(24, 343); ctx.lineTo(W - 24, 343); ctx.stroke();
  hitAreas.push({ x: 18, y: 215, w: W - 36, h: 58, action: 'username' }, { x: 18, y: 290, w: W - 36, h: 58, action: 'password' });
  hitAreas.push(button(24, 374, W - 48, 48, state.mode === 'login' ? '登录并进入大厅' : '注册并进入大厅', 'submitAuth', true));
  hitAreas.push(button(24, 438, (W - 60) / 2, 42, state.mode === 'login' ? '切换注册' : '切换登录', 'toggleAuth'));
  hitAreas.push(button(36 + (W - 60) / 2, 438, (W - 60) / 2, 42, '连接配置', 'endpoint'));
  hitAreas.push(button(24, 494, W - 48, 44, '微信快捷登录', 'wechatLogin'));
  ctx.fillStyle = '#c45445'; ctx.font = '13px sans-serif'; ctx.fillText(state.notice, 24, 565);
  ctx.fillStyle = '#71808a'; ctx.font = '11px sans-serif'; ctx.fillText('本地联调也可使用开发测试账号', 24, H - 24);
}
function drawLobby() {
  header('本地大厅', state.username + ' · ' + (state.connected ? '已连接' : '未连接'));
  ctx.fillStyle = '#17212b'; ctx.font = 'bold 19px sans-serif'; ctx.textAlign = 'left'; ctx.fillText('开始一局', 24, 124);
  ctx.fillStyle = '#53616b'; ctx.font = '13px sans-serif'; ctx.fillText('创建房间后，把房间码分享给朋友', 24, 149);
  hitAreas.push(button(24, 180, W - 48, 52, '创建房间', 'createRoom', true));
  ctx.fillStyle = '#53616b'; ctx.font = '13px sans-serif'; ctx.fillText('已有房间码', 24, 279);
  ctx.fillStyle = '#17212b'; ctx.font = '18px sans-serif'; ctx.fillText(state.roomCode || '点击输入房间码', 24, 311);
  ctx.strokeStyle = '#9aa5aa'; ctx.beginPath(); ctx.moveTo(24, 321); ctx.lineTo(W - 24, 321); ctx.stroke();
  hitAreas.push({ x: 18, y: 265, w: W - 36, h: 65, action: 'roomCode' });
  hitAreas.push(button(24, 345, W - 48, 50, '加入房间', 'joinRoom'));
  hitAreas.push(button(24, 420, W - 48, 42, '连接配置', 'endpoint'));
  ctx.fillStyle = '#c45445'; ctx.font = '13px sans-serif'; ctx.fillText(state.notice, 24, 510);
}
function drawRoom() {
  header('房间 ' + (state.roomCode || '默认房间'), state.role === 'drawer' ? '你是画手 · 画出词语' : '你是猜手 · 输入答案');
  const top = 88, boardH = Math.max(190, H - 350);
  ctx.fillStyle = '#ffffff'; ctx.fillRect(14, top, W - 28, boardH); ctx.strokeStyle = '#17212b'; ctx.lineWidth = 2; ctx.strokeRect(14, top, W - 28, boardH);
  for (let i = 0; i < state.strokes.length; i += 1) drawStroke(state.strokes[i], top, boardH);
  ctx.fillStyle = '#53616b'; ctx.font = '12px sans-serif'; ctx.textAlign = 'left';
  ctx.fillText(state.round ? ('第 ' + state.round.roundNumber + ' 轮 · ' + (state.round.remaining || state.round.duration || 60) + ' 秒') : '等待其他玩家', 20, top - 10);
  ctx.fillText('玩家 ' + state.players.length, W - 80, top - 10);
  let y = top + boardH + 25; ctx.fillStyle = '#17212b'; ctx.font = 'bold 14px sans-serif';
  ctx.fillText(state.word ? '本轮词语：' + state.word : '本轮词语：仅画手可见', 20, y);
  y += 22; ctx.fillStyle = '#53616b'; ctx.font = '12px sans-serif';
  for (let i = Math.max(0, state.messages.length - 3); i < state.messages.length; i += 1) { ctx.fillText(state.messages[i].text, 20, y); y += 17; }
  hitAreas.push({ x: 14, y: top, w: W - 28, h: boardH, action: 'canvas' });
  hitAreas.push(button(20, H - 92, (W - 52) / 2, 44, state.role === 'drawer' ? '清空画布' : '输入答案', state.role === 'drawer' ? 'clear' : 'guess', state.role !== 'drawer'));
  hitAreas.push(button(32 + (W - 52) / 2, H - 92, (W - 52) / 2, 44, '退出房间', 'lobby'));
  if (state.gameOver) { ctx.fillStyle = 'rgba(23,33,43,.86)'; ctx.fillRect(18, top + boardH / 2 - 45, W - 36, 90); ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.font = 'bold 19px sans-serif'; ctx.fillText('本局结束', W / 2, top + boardH / 2 - 8); ctx.font = '13px sans-serif'; ctx.fillText('房主可发送 play_again 开始下一局', W / 2, top + boardH / 2 + 20); }
}
function drawStroke(s, top, boardH) {
  if (!s) return;
  const x0 = 14 + s.x0 * (W - 28), x1 = 14 + s.x1 * (W - 28), y0 = top + s.y0 * boardH, y1 = top + s.y1 * boardH;
  ctx.strokeStyle = s.color || '#17212b'; ctx.lineWidth = Math.max(1, (s.width || 4) * W / 390); ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
}
function authenticateMessage() {
  if (state.socketAuthType === 'session_token') return { type: 'session_token', token: state.token };
  const firstLogin = !state.authenticated;
  return { type: firstLogin && state.mode === 'register' ? 'register' : 'join', username: state.username, password: state.password };
}
function connect() {
  if (!state.endpoint) { setNotice('请先填写 WebSocket 地址'); return; }
  if (state.socket) try { state.socket.close(); } catch (e) {}
  setNotice('正在连接…');
  state.socket = wx.connectSocket({ url: state.endpoint });
  state.socket.onOpen(() => { state.connected = true; state.socket.send({ data: JSON.stringify(authenticateMessage()) }); });
  state.socket.onMessage((event) => { try { handleMessage(JSON.parse(event.data || '{}')); } catch (e) { setNotice('收到无效服务器消息'); } });
  state.socket.onClose(() => { state.connected = false; state.socket = null; if (state.hidden) return; if (state.authenticated && state.reconnects < 3) { state.reconnects += 1; state.reconnectTimer = setTimeout(connect, 1200 * state.reconnects); setNotice('连接断开，正在自动重连（' + state.reconnects + '/3）'); } else setNotice('连接已断开'); });
  state.socket.onError(() => setNotice('连接失败，请检查地址和服务端'));
}
function handleMessage(m) {
  const type = m.type;
  if (type === 'auth_error') { setNotice(m.message); return; }
  if (type === 'lobby') { state.authenticated = true; state.mode = 'login'; state.page = 'lobby'; setNotice('登录成功'); draw(); return; }
  if (type === 'joined') { state.page = 'room'; state.roomCode = m.roomCode || ''; state.clientId = m.clientId || ''; state.role = m.role || 'guesser'; state.color = m.color || state.color; state.strokes = m.strokes || []; state.gameOver = !!m.gameOver; state.round = m.round || null; addMessage('已进入房间', true); draw(); return; }
  if (type === 'presence') { state.players = m.players || []; draw(); return; }
  if (type === 'round_started') { state.round = m; state.word = ''; state.gameOver = false; addMessage('第 ' + m.roundNumber + ' 轮开始', true); draw(); return; }
  if (type === 'word') { state.word = m.word || ''; draw(); return; }
  if (type === 'stroke') { state.strokes.push(m); draw(); return; }
  if (type === 'clear') { state.strokes = []; draw(); return; }
  if (type === 'chat') { addMessage(text(m.playerName, '玩家') + '：' + text(m.text, ''), false); draw(); return; }
  if (type === 'correct_guess') { addMessage(text(m.playerName, '玩家') + ' 猜对了', true); draw(); return; }
  if (type === 'game_over') { state.gameOver = true; addMessage(text(m.message, '游戏结束'), true); draw(); return; }
  if (type === 'game_reset') { state.gameOver = false; state.strokes = []; state.messages = []; draw(); return; }
  if (type === 'error' || type === 'notice') { setNotice(m.message); if (type === 'error') addMessage(m.message, true); draw(); }
}
function submitGuess() { openInput('输入答案或聊天', '', (value) => { if (value.trim()) send({ type: 'guess', text: value.trim() }); }); }
function handleAction(action, x, y) {
  if (action === 'username') openInput('用户名', state.username, (v) => { state.username = v.trim(); draw(); });
  else if (action === 'password') openInput('密码', '', (v) => { state.password = v; draw(); });
  else if (action === 'endpoint') openInput('WebSocket 地址', state.endpoint, (v) => { state.endpoint = v.trim(); saveSettings(); draw(); });
  else if (action === 'roomCode') openInput('房间码', state.roomCode, (v) => { state.roomCode = v.trim(); draw(); });
  else if (action === 'toggleAuth') { state.mode = state.mode === 'login' ? 'register' : 'login'; state.notice = ''; draw(); }
  else if (action === 'wechatLogin') loginWithWechat();
  else if (action === 'submitAuth') { if (!state.username || !state.password) setNotice('请输入用户名和密码'); else { state.socketAuthType = 'password'; saveSettings(); connect(); } }
  else if (action === 'createRoom') send({ type: 'create_room', roomCode: 'new' });
  else if (action === 'joinRoom') { if (!state.roomCode) setNotice('请先输入房间码'); else send({ type: 'join_room', roomCode: state.roomCode }); }
  else if (action === 'clear') { state.strokes = []; send({ type: 'clear' }); draw(); }
  else if (action === 'guess') submitGuess();
  else if (action === 'lobby') { send({ type: 'leave_room' }); state.page = 'lobby'; state.strokes = []; draw(); }
  else if (action === 'canvas' && state.role === 'drawer') state.touch = point(x, y);
}
function point(x, y) { const top = 88, boardH = Math.max(190, H - 350); return { x: Math.max(0, Math.min(1, (x - 14) / (W - 28))), y: Math.max(0, Math.min(1, (y - top) / boardH)) }; }
wx.onTouchStart((e) => { const t = e.touches[0]; const action = hit(t.clientX, t.clientY); if (action) handleAction(action, t.clientX, t.clientY); });
wx.onTouchMove((e) => { if (!state.touch || state.role !== 'drawer') return; const t = e.touches[0], p = point(t.clientX, t.clientY); const s = { type: 'stroke', id: Date.now().toString(36) + Math.random().toString(36).slice(2), x0: state.touch.x, y0: state.touch.y, x1: p.x, y1: p.y, color: state.color, width: 4 }; state.strokes.push(s); send(s); state.touch = p; draw(); });
wx.onTouchEnd(() => { state.touch = null; });
wx.onHide(() => { state.hidden = true; if (state.reconnectTimer) clearTimeout(state.reconnectTimer); state.reconnectTimer = null; if (state.socket) state.socket.close(); });
wx.onShow(() => { state.hidden = false; if (state.authenticated && !state.connected && state.reconnects < 3) { state.reconnects += 1; connect(); } });
draw();
