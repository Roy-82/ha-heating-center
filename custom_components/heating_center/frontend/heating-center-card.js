/* HA Heating Center – compact Lovelace card; version 0.3.0-beta.12.
   No external libraries. Data and permitted actions stay inside HA WebSocket. */
(() => {
"use strict";
const VERSION="0.3.0-beta.12";
const esc=v=>String(v??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const fmt=v=>v===null||v===undefined||v===""||!Number.isFinite(Number(v))?"–":Number(v).toLocaleString("de-DE",{maximumFractionDigits:1});
const modes={home:"Zuhause",away:"Abwesend",vacation:"Urlaub"};
const profiles=[["eco","Eco",120],["comfort","Komfort",120],["boost","Boost",30]];
const CSS=[
":host{display:block;min-width:0}*{box-sizing:border-box}",
"ha-card{display:block;overflow:hidden;background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color,#253244);border-radius:var(--ha-card-border-radius,16px)}",
".wrap{padding:15px 16px 17px}.head{display:flex;gap:9px;align-items:center;justify-content:space-between;margin-bottom:9px}",
".brand{display:flex;gap:9px;align-items:center;min-width:0}.brand img{width:36px;height:36px;object-fit:contain;border-radius:10px}",
".name{font-weight:750;font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sub{font-size:11px;color:var(--secondary-text-color,#687889);margin-top:1px}",
".open{border:1px solid var(--divider-color,#dce2e9);padding:7px 9px;border-radius:9px;background:transparent;color:var(--primary-text-color,#334);cursor:pointer;white-space:nowrap;font:inherit;font-size:12px}",
".stats{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 11px;font-size:11px;color:var(--secondary-text-color,#687889)}",
".dot{height:7px;width:7px;border-radius:50%;display:inline-block;background:#21a578;margin-right:4px}.stats strong{color:var(--primary-text-color)}",
".tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}",
".tile{border:1px solid var(--divider-color,#dce3e9);background:var(--secondary-background-color,#f8fafc);border-radius:12px;padding:11px;min-width:0}",
".title{display:flex;align-items:center;justify-content:space-between;gap:6px;font-size:13px;font-weight:750;min-width:0}",
".title span:first-child{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
".mark{display:inline-block;border-radius:5px;font-size:10px;font-weight:650;padding:2px 5px;flex:none;background:var(--card-background-color,#fff);color:var(--secondary-text-color,#6c7787)}",
".mark.on{color:#22794b;background:rgba(40,180,90,.12)}",
".temperatures{display:flex;align-items:baseline;gap:10px;margin-top:7px;flex-wrap:wrap}",
".temp{font-size:21px;line-height:1.2;font-weight:770;letter-spacing:-.6px;white-space:nowrap}",
".temp small{font-size:10px;font-weight:550;color:var(--secondary-text-color,#637282);letter-spacing:0;margin-right:4px}",
".temp.set{font-size:17px;font-weight:650;letter-spacing:-.2px}",
".meta{display:flex;align-items:center;flex-wrap:wrap;gap:5px;margin:7px 0 10px;min-height:17px;font-size:10px}",
".chip{border-radius:5px;padding:2px 6px;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#e4e7eb);color:var(--secondary-text-color,#697887)}",
".chip.heat{background:rgba(243,144,38,.13);color:#b46809;border-color:transparent}",
".chip.need{background:rgba(243,144,38,.10);color:#b46809;border-color:transparent}",
".chip.warn{background:rgba(205,79,57,.10);color:#b54b39;border-color:transparent}",
".actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}",
".actions button{min-width:0;cursor:pointer;border:1px solid var(--divider-color,#dce3e9);background:var(--card-background-color,#fff);color:var(--primary-text-color,#324252);border-radius:7px;padding:7px 2px;font:inherit;font-size:11px;font-weight:650}",
".actions button.boost{color:#d16c10;border-color:rgba(211,123,41,.45)}",
".actions button:hover:not(:disabled){background:var(--primary-color,#2185d0);color:white}",
".actions button:disabled{opacity:.43;cursor:not-allowed}.actions button.wait{opacity:.6}",
".message{font-size:12px;padding:8px 10px;border-radius:8px;background:var(--secondary-background-color,#eaf3fb);margin:0 0 10px}",
".message.error{background:rgba(218,75,61,.12);color:#b94735}.empty{padding:20px 0;color:var(--secondary-text-color,#6a7885);text-align:center;font-size:13px}",
".footer{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-top:10px;font-size:10px;color:var(--secondary-text-color,#677689)}",
":host([data-columns='1']) .tiles{grid-template-columns:1fr}",
"@media(max-width:640px){.tiles{grid-template-columns:1fr}.wrap{padding:12px}.tile{padding:10px}}"
].join("");
class HeatingCenterCard extends HTMLElement {
 constructor(){
  super();this.attachShadow({mode:"open"});
  this._config=null;this._hass=null;this._data=null;this._error="";this._notice="";
  this._loading=false;this._working=null;this._timer=null;this._refs=new Map();
  this.shadowRoot.addEventListener("click",event=>this._click(event));
 }
 setConfig(config){
  if(!config||typeof config!=="object")throw Error("Heating Center: Ungültige Kartenkonfiguration");
  if(config.rooms!==undefined&&(!Array.isArray(config.rooms)||!config.rooms.every(x=>typeof x==="string")))throw Error("Heating Center: rooms muss eine Liste von Raum-IDs sein");
  if(config.columns!==undefined&&![1,2,"auto"].includes(config.columns))throw Error("Heating Center: columns muss 1, 2 oder auto sein");
  this._config={title:config.title===undefined?"Heating Center":String(config.title),
   rooms:config.rooms||null,columns:config.columns||"auto",show_group:config.show_group!==false};
  this.setAttribute("data-columns",this._config.columns===1?"1":"2");
  this._render();
  if(this.isConnected&&this._hass)void this._load();
 }
 set hass(hass){
  this._hass=hass;
  if(!this._config||!this.isConnected)return;
  if(!this._data){if(!this._loading)void this._load();return;}
  let changed=false;const refs=new Map();
  for(const room of Object.values(this._data.rooms||{})){
   for(const id of [...(room.climates||[]),room.sensor].filter(Boolean)){
    const state=hass.states?.[id];refs.set(id,state);
    if(this._refs.get(id)!==state)changed=true;
   }
  }
  this._refs=refs;
  if(changed&&!this._working)this._render();
 }
 connectedCallback(){
  if(!this._timer)this._timer=setInterval(()=>{if(!this._loading&&!this._working)void this._load();},45000);
  if(this._config&&this._hass&&!this._data)void this._load();
 }
 disconnectedCallback(){if(this._timer)clearInterval(this._timer);this._timer=null;}
 getCardSize(){const n=this._selected().length||1;return Math.max(4,Math.ceil(n/(this._config?.columns===1?1:2))*2+3);}
 static getStubConfig(){return {title:"Heating Center",columns:"auto"};}
 _selected(){
  const all=Object.entries(this._data?.rooms||{}), ids=this._config?.rooms;
  const list=ids?all.filter(([id])=>ids.includes(id)):all;
  return list.sort((a,b)=>ids?ids.indexOf(a[0])-ids.indexOf(b[0]):String(a[1].name||a[0]).localeCompare(String(b[1].name||b[0]),"de"));
 }
 _watch(){
  this._refs=new Map();
  for(const room of Object.values(this._data?.rooms||{})){
   for(const id of [...(room.climates||[]),room.sensor].filter(Boolean))this._refs.set(id,this._hass?.states?.[id]);
  }
 }
 async _load(){
  if(!this._hass||!this._config||this._loading||this._working)return;
  this._loading=true;
  try{
   const result=await this._hass.callWS({type:"heating_center/get"});
   if(!result||typeof result.rooms!=="object"||!result.entry_id)throw Error("Keine gültigen Raumdaten von Heating Center");
   const before=this._data?JSON.stringify({rooms:this._data.rooms,demand:this._data.demand,warnings:this._data.warnings,mode:this._data.mode}):null;
   this._data=result;this._error="";
   const after=JSON.stringify({rooms:result.rooms,demand:result.demand,warnings:result.warnings,mode:result.mode});
   this._watch();
   if(before!==after||!this.shadowRoot.querySelector(".tiles"))this._render();
  }catch(e){this._error=e?.message||String(e);this._render();}
  finally{this._loading=false;}
 }
 _actual(room,id){
  const st=this._hass?.states?.[room.sensor];
  if(st&&!["unknown","unavailable"].includes(st.state)){
   const v=Number(st.state);if(Number.isFinite(v)&&v>=-30&&v<=65)return v;
  }
  const snapshot=this._data?.demand?.[id]?.measured;
  if(snapshot!==null&&snapshot!==undefined&&Number.isFinite(Number(snapshot)))return Number(snapshot);
  const value=this._hass?.states?.[room.climates?.[0]]?.attributes?.current_temperature;
  return value!==null&&value!==undefined&&Number.isFinite(Number(value))?Number(value):null;
 }
 _heat(room,id){
  const cl=(room.climates||[]).map(n=>this._hass?.states?.[n]).filter(Boolean);
  const states=cl.map(st=>String(st.attributes?.hvac_action||st.attributes?.running_state||"").toLowerCase());
  if(states.some(s=>["heating","heat"].includes(s)))return ["Heizt","heat"];
  if(states.some(s=>["idle","off","cooling"].includes(s)))return ["Heizt nicht",""];
  if(this._data?.demand?.[id]?.active)return ["Wärmebedarf","need"];
  return ["Bereit",""];
 }
 _room(id,room){
  const target=this._data?.demand?.[id]?.target??this._data?.calculated_targets?.[id]??room.target;
  const [heat,kind]=this._heat(room,id),warning=(this._data?.warnings?.[id]||[]).filter(s=>s!=="Raumsteuerung noch nicht aktiviert").length;
  const ready=!!(room.enabled&&this._data?.session_admin),blocked=!!this._working;
  const buttons=profiles.map(([profile,label,duration])=>'<button type="button" data-act="profile" data-room="'+esc(id)+'" data-profile="'+profile+'" data-minutes="'+duration+'" class="'+(profile==="boost"?"boost ":"")+(this._working===id?"wait":"")+'" '+(!ready||blocked?"disabled":"")+' aria-label="'+esc(label+" für "+room.name)+'">'+label+'</button>').join("");
  return '<section class="tile" aria-label="'+esc(room.name)+'">'+
   '<div class="title"><span title="'+esc(room.name)+'">'+esc(room.name||id)+'</span><span class="mark '+(room.enabled?"on":"")+'">'+(room.enabled?"Aktiv":"Inaktiv")+'</span></div>'+
   '<div class="temperatures"><div class="temp"><small>Ist</small>'+fmt(this._actual(room,id))+'°</div>'+
   '<div class="temp set"><small>Soll</small>'+fmt(target)+'°</div></div>'+
   '<div class="meta"><span class="chip '+kind+'">'+(room.enabled?heat:"Steuerung aus")+'</span>'+
   '<span class="chip">'+(room.schedule_enabled?"Plan an":"Plan aus")+'</span>'+
   (warning?'<span class="chip warn" title="'+esc((this._data.warnings[id]||[]).join(" · "))+'">⚠ '+warning+'</span>':"")+
   (room.group&&this._config?.show_group?'<span class="chip">'+esc(room.group)+'</span>':"")+'</div>'+
   '<div class="actions">'+buttons+'</div></section>';
 }
 _render(){
  if(!this._config)return;
  const rooms=this._selected(),active=rooms.filter(([,r])=>r.enabled).length,
   demand=rooms.filter(([id])=>this._data?.demand?.[id]?.active).length;
  const msg=this._error?'<div class="message error" role="alert">'+esc(this._error)+'</div>':
   (this._notice?'<div class="message" role="status">'+esc(this._notice)+'</div>':"");
  const content=!this._data?'<div class="empty">Verbinde mit Heating Center …</div>':
   (!rooms.length?'<div class="empty">Noch keine Räume eingerichtet.</div>':'<div class="tiles">'+rooms.map(([id,room])=>this._room(id,room)).join("")+'</div>');
  this.shadowRoot.innerHTML='<style>'+CSS+'</style><ha-card><div class="wrap"><div class="head">'+
   '<div class="brand"><img src="/heating_center_assets/heating-center-logo.svg" alt=""><div><div class="name">'+esc(this._config.title)+'</div>'+
   '<div class="sub">'+esc(modes[this._data?.mode]||"Raumübersicht")+' · '+esc(active)+'/'+esc(rooms.length)+' aktiv</div></div></div>'+
   '<button type="button" class="open" data-act="open" aria-label="Heating Center öffnen">Öffnen ↗</button></div>'+
   '<div class="stats"><span><i class="dot"></i><strong>'+esc(active)+'</strong> Räume aktiv</span>'+
   '<span>·</span><span><strong>'+esc(demand)+'</strong> mit Wärmebedarf</span></div>'+
   msg+content+'<div class="footer"><span>Ist/Soll in °C · Boost 30 Min. · Eco/Komfort 2 Std.</span><span>β12</span></div></div></ha-card>';
 }
 async _click(event){
  const el=event.target?.closest?.("button[data-act]");if(!el)return;
  if(el.dataset.act==="open"){
   history.pushState(null,"","/heating_center");window.dispatchEvent(new Event("location-changed"));return;
  }
  if(el.dataset.act!=="profile"||this._working)return;
  const roomId=el.dataset.room,profile=el.dataset.profile,minutes=Number(el.dataset.minutes);
  const room=this._data?.rooms?.[roomId];
  if(!room?.enabled||!this._data?.session_admin){this._error="Zum Steuern muss der Raum aktiv sein und ein Administrator angemeldet sein.";this._render();return;}
  if(!["eco","comfort","boost"].includes(profile))return;
  this._working=roomId;this._error="";this._notice="Setze "+(profiles.find(p=>p[0]===profile)?.[1]||profile)+" für "+room.name+" …";this._render();
  try{
   const result=await this._hass.callWS({type:"heating_center/execute",config_entry_id:this._data.entry_id,
    action:"apply_profile",data:{room_id:roomId,profile,minutes}});
   if(!result?.ok||!result.snapshot?.rooms?.[roomId])throw Error("Heating Center hat den Profilwechsel nicht bestätigt");
   this._data={...result.snapshot,session_admin:this._data.session_admin};
   this._notice=(profiles.find(p=>p[0]===profile)?.[1]||profile)+" für "+room.name+" aktiviert ("+minutes+" Min.)";
   this._watch();
  }catch(e){this._error="Profil konnte nicht gesetzt werden: "+(e?.message||String(e));this._notice="";}
  finally{this._working=null;this._render();}
 }
}
if(!customElements.get("heating-center-card"))customElements.define("heating-center-card",HeatingCenterCard);
window.customCards=window.customCards||[];
if(!window.customCards.some(card=>card.type==="heating-center-card"))
 window.customCards.push({type:"heating-center-card",name:"Heating Center – Kompakt",description:"Übersicht für bis zu zehn und mehr Heizräume mit Temperatur, Wochenplan und Eco-/Komfort-/Boost-Profilen.",preview:false});
console.info("HA Heating Center Lovelace card "+VERSION+" loaded");
})();