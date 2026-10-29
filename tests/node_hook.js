const fs = require('fs');
const out = process.env.HWID_LOG || 'C:\\SHARE\\hwid\\logs\\hwid_payload.jsonl';
function log(s) {
  try { fs.appendFileSync(out, JSON.stringify({t:new Date().toISOString(),pid:process.pid,tag:process.env.HWID_TAG||'',data:s})+'\n'); } catch(e) {}
}
function patch(WS) {
  if (!WS || !WS.prototype || WS.prototype.__hwidHooked) return;
  const orig = WS.prototype.send;
  WS.prototype.send = function(data) {
    try {
      let s = Buffer.isBuffer(data) ? data.toString('utf8') : (typeof data === 'string' ? data : String(data));
      log(s);
    } catch(e) {}
    return orig.apply(this, arguments);
  };
  WS.prototype.__hwidHooked = true;
}
const Module = require('module');
const oldLoad = Module._load;
Module._load = function(request, parent, isMain) {
  const exp = oldLoad.apply(this, arguments);
  if (request === 'ws' || /[\\/]ws$/.test(request)) {
    patch(exp);
    if (exp && exp.WebSocket) patch(exp.WebSocket);
  }
  return exp;
};
if (typeof WebSocket !== 'undefined') patch(WebSocket);
