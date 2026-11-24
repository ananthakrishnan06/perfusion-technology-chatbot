"use strict";

const root = document.querySelector("#main");
const sidebar = document.querySelector("#sidebar");
const nav = sidebar.querySelector("nav");
const dialog = document.querySelector("#dialog");
const content = document.querySelector("#dialog-body");
const toast = document.querySelector("#toast");
const sessionHeaders = {"X-Perfusion-Session": "cookie"};
const labels = ["Overview", "Study materials", "People", "Sign-ins", "Usage reports", "Recent activity", "Settings"];
let active = "";
let viewVersion = 0;
let toastTimer;
let previewUrl;

function tag(name, text) {
  const node = document.createElement(name);
  if (text !== undefined) node.textContent = text;
  return node;
}
function button(text, action) {
  const control = tag("button", text);
  control.type = "button";
  control.addEventListener("click", async () => {
    control.disabled = true;
    try { await action(); } catch (error) { notify(error.message); }
    finally { control.disabled = false; }
  });
  return control;
}
function notify(text) {
  toast.textContent = text;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.textContent = ""; }, 6000);
}
async function api(path, body, method = body === undefined ? "GET" : "POST") {
  const options = {method, credentials:"same-origin", headers:{...sessionHeaders}};
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch("/api/v1" + path, options);
  } catch {
    throw new Error("Couldn’t connect. Check your internet connection and try again.");
  }
  if (response.status === 401) {
    location.replace("/");
    throw new Error("Your session ended.");
  }
  if (!response.ok) {
    const descriptions = {
      400: path === "/admin/password"
        ? "Check your initial password and choose a different new password."
        : "Check the information you entered and try again.",
      403: "Your account doesn’t have permission to do that.",
      404: "That item is no longer available.",
      409: "This change conflicts with an existing item.",
      413: "The files are too large. Try uploading fewer or smaller files.",
      422: "Check the information you entered and try again.",
      429: "Too many attempts. Please wait a moment and try again."
    };
    throw new Error(descriptions[response.status] ?? "Something went wrong. Please try again.");
  }
  if (response.status === 204) return;
  return response;
}
async function data(path, body, method) { return (await api(path, body, method)).json(); }
function container(...children) {
  const box = tag("div");
  box.className = "toolbar";
  box.append(...children);
  return box;
}
function panel(title) {
  const box = tag("section");
  box.className = "panel";
  box.append(tag("h2", title));
  return box;
}
function table(headers, rows) {
  const box = tag("div");
  box.className = "table-wrap";
  const t = tag("table"), head = tag("thead"), tr = tag("tr"), body = tag("tbody");
  for (const header of headers) { const cell = tag("th", header); cell.scope = "col"; tr.append(cell); }
  head.append(tr);
  for (const row of rows) {
    const line = tag("tr");
    for (const value of row) {
      const cell = tag("td");
      cell.append(value instanceof Node ? value : String(value ?? "Unavailable"));
      line.append(cell);
    }
    body.append(line);
  }
  t.append(head, body);
  box.append(rows.length ? t : tag("p", "No results."));
  return box;
}
function field(label, name, value = "", type = "text") {
  const wrapper = tag("label", label), input = tag("input");
  input.name = name;
  input.type = type;
  if (type === "checkbox") input.checked = value;
  else input.value = value ?? "";
  wrapper.append(input);
  return [wrapper, input];
}
function select(values) {
  const node = tag("select");
  for (const [value, label] of values) { const option = tag("option", label); option.value = value; node.append(option); }
  return node;
}
const documentStatus = {indexed:"Ready to use", failed:"Needs attention", processing:"Getting ready", already_indexed:"Already in the library"};
const accountStatus = {active:"Active", blocked:"Temporarily blocked", suspended:"Suspended"};
const sessionStatus = {online:"Online", offline:"Offline", revoked:"Signed out", expired:"Expired"};

function date(value) { return value ? new Date(value).toLocaleString() : "Unavailable"; }
function refresh() { return show(active); }
function confirmAction(message, action) {
  content.replaceChildren(tag("p", message), button("Confirm", async () => { await action(); dialog.close(); }));
  dialog.showModal();
}
function chart(title, data, line = false) {
  const box = panel(title), entries = Object.entries(data ?? {});
  if (!entries.length) { box.append(tag("p", "No recorded data for this period.")); return box; }
  const sorted = entries.sort(([a],[b])=>a.localeCompare(b));
  const recent = sorted.slice(-31);
  const detail = tag("p", "Select a point for its value.");
  if (line) {
    const canvas = tag("canvas");
    canvas.width = 480; canvas.height = 145;
    canvas.setAttribute("aria-label", title);
    const context = canvas.getContext("2d");
    const max = Math.max(1, ...recent.map(([,value])=>value));
    context.strokeStyle = "#b37544"; context.lineWidth = 3; context.beginPath();
    recent.forEach(([,value],i)=>{
      const x = 10 + i * 460 / Math.max(1, recent.length-1), y = 130 - value * 115 / max;
      if (i === 0) context.moveTo(x,y); else context.lineTo(x,y);
    });
    context.stroke();
    box.append(canvas);
  }
  const bars = tag("div"); bars.className = "chart";
  const max = Math.max(1,...recent.map(([,n])=>n));
  for (const [key,n] of recent) {
    const bar = button("", () => { detail.textContent = key + " · " + n; });
    bar.style.height = (8+100*n/max)+"px"; bar.title = key + " · " + n;
    bar.setAttribute("aria-label",bar.title); bars.append(bar);
  }
  box.append(bars, detail);
  return box;
}
async function overview() {
  const [metrics, usage] = await Promise.all([data("/admin/overview"),data("/admin/usage")]);
  const cards = tag("div"); cards.className = "cards";
  const titles = {users:"Registered users",active:"People online",pdfs:"Uploaded PDFs",indexed:"PDFs ready to use",requests:"Questions asked",today:"Questions today",failed:"Questions without an answer"};
  for (const [key,label] of Object.entries(titles)) {
    const card = tag("div"); card.className = "card";
    card.append(tag("span",label),tag("strong",metrics[key] ?? "Unavailable")); cards.append(card);
  }
  const charts = tag("div"); charts.className = "charts";
  charts.append(chart("Daily usage",usage.daily,true),chart("User activity",usage.active_users),chart("Document uploads",usage.uploads));
  return [cards,charts];
}
const categories = ["course","semester","subject","module","topic"];
function categoryFields(doc = {}) {
  const fields = tag("div"); fields.className = "fields";
  const inputs = {};
  for (const key of categories) {
    const [label,input] = field(key[0].toUpperCase()+key.slice(1),key,doc[key]);
    input.maxLength = 100;
    fields.append(label); inputs[key]=input;
  }
  return [fields, () => Object.fromEntries(categories.map(key=>[key,inputs[key].value.trim()]))];
}
function upload(files, tags, progress, replacement = "") {
  return new Promise((resolve,reject)=>{
    const form = new FormData();
    for (const file of files) form.append("files",file);
    form.append("categories",JSON.stringify(tags));
    if (replacement) form.append("replace",replacement);
    const xhr = new XMLHttpRequest();
    xhr.open("POST","/api/v1/admin/documents/upload");
    xhr.setRequestHeader("X-Perfusion-Session","cookie");
    xhr.responseType = "json";
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) progress.value = event.loaded / event.total;
    };
    xhr.upload.onload = () => { progress.removeAttribute("value"); };
    xhr.onerror = () => reject(new Error("Upload connection failed."));
    xhr.onload = () => {
      if (xhr.status===401) location.replace("/");
      if (xhr.status>=200 && xhr.status<300) resolve(xhr.response);
      else if (xhr.status === 413) reject(new Error("The files are too large. Try uploading fewer or smaller files."));
      else if (xhr.status === 422) reject(new Error("Choose a valid PDF and check the categories."));
      else reject(new Error("The upload didn’t finish. Please try again."));
    };
    xhr.send(form);
  });
}
function uploader(doc) {
  const box = panel(doc ? "Replace PDF" : "Upload PDFs");
  const [fields, values] = categoryFields(doc);
  const drop = tag("label","Drop PDF files here or choose files"); drop.className="drop";
  const picker = tag("input");
  picker.type="file"; picker.accept=".pdf,application/pdf"; picker.multiple=!doc; drop.append(picker);
  const status=tag("p"), progress=tag("progress"); progress.max=1; progress.hidden=true;
  let selected=[];
  function choose(files){selected=Array.from(files);status.textContent=selected.map(f=>f.name).join(", ");}
  picker.onchange=()=>choose(picker.files);
  drop.ondragover=e=>{e.preventDefault();drop.classList.add("dragging");};
  drop.ondragleave=()=>drop.classList.remove("dragging");
  drop.ondrop=e=>{e.preventDefault();drop.classList.remove("dragging");choose(e.dataTransfer.files);};
  box.append(fields,drop,status,progress,button(doc ? "Upload replacement" : "Add to library",async()=>{
    if (!selected.length || (doc && selected.length!==1)) throw new Error("Choose a PDF first.");
    progress.hidden=false;progress.value=0;
    try {
      const result=await upload(selected,values(),progress,doc?.document_id);
      notify(result.map(row=>row.original_filename+" · "+(documentStatus[row.processing_status] ?? "Check the library")).join(", "));
      if (dialog.open) dialog.close();
      await refresh();
    } finally { progress.hidden=true; }
  }));
  return box;
}
async function documents() {
  const rows=await data("/admin/documents");
  const [searchLabel,search]=field("Search PDFs","search","","search");
  const [subjectLabel,subject]=field("Subject or module","category");
  const status=select([["","All PDFs"],["indexed","Ready to use"],["failed","Needs attention"]]);
  status.setAttribute("aria-label","Processing status");
  const listing=tag("div");
  function draw() {
    const q=search.value.toLowerCase(), filter=subject.value.toLowerCase();
    listing.replaceChildren(table(["Document","Categories","Size","Uploaded","Pages","Status","Actions"],rows.filter(d=>
      d.filename.toLowerCase().includes(q)&&(!status.value||d.status===status.value)&&[d.subject,d.module].join(" ").toLowerCase().includes(filter)
    ).map(d=>[d.filename,categories.map(key=>d[key]).filter(Boolean).join(" / "),Math.ceil(d.file_size_bytes/1024)+" KB",date(d.uploaded_at),d.total_pages,documentStatus[d.status] ?? "Unavailable",container(
      button("Preview",async()=>{
        const image=tag("img");image.alt="PDF page";
        const [label,page]=field("Page","page",1,"number");page.min=1;page.max=d.total_pages||1;
        async function load(){const res=await api("/admin/documents/"+d.document_id+"/preview?page="+encodeURIComponent(page.value));if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=URL.createObjectURL(await res.blob());image.src=previewUrl;}
        await load();content.replaceChildren(tag("h2",d.filename),label,button("Show page",load),image);dialog.showModal();
      }),
      button("Edit categories",()=>{const [fields,values]=categoryFields(d);content.replaceChildren(fields,button("Save",async()=>{await data("/admin/documents/"+d.document_id,values(),"PATCH");dialog.close();await refresh();}));dialog.showModal();}),
      button("Replace",()=>{content.replaceChildren(uploader(d));dialog.showModal();}),
      ...(d.status==="failed"?[button("Try again",async()=>{const result=await data("/admin/documents/"+d.document_id+"/reprocess",{});notify(documentStatus[result.processing_status] ?? "Check the library");await refresh();})]:[]),
      button("Delete",()=>confirmAction("Delete "+d.filename+" from the library?",async()=>{await api("/admin/documents/"+d.document_id,undefined,"DELETE");await refresh();}))
    )])));
  }
  search.oninput=draw;subject.oninput=draw;status.onchange=draw;draw();
  return [uploader(),container(searchLabel,subjectLabel,status),listing];
}
async function users() {
  const rows=await data("/admin/users");
  const [label,search]=field("Search by name","search","","search");
  const status=select([["","All statuses"],["active","Active"],["blocked","Blocked"],["suspended","Suspended"]]);status.setAttribute("aria-label","Account status");
  const listing=tag("div");
  function draw() {
    listing.replaceChildren(table(["Name","Status","Joined","Last sign-in","Last active","Questions asked","Access","Actions"],
      rows.filter(row=>row.username.toLowerCase().includes(search.value.toLowerCase())&&(!status.value||status.value===row.status)).map(row=>{
        const perform=async(action,extra={})=>{await data("/admin/users/"+encodeURIComponent(row.id),{action,...extra});notify("Account updated.");await refresh();};
        const actions=container(button("Activity",()=>show("Usage reports",row.id)));
        if(row.role!=="admin"){
          actions.append(button("Sign out everywhere",()=>confirmAction("End every session for "+row.username+"?",()=>perform("logout"))),
            button(row.status==="active"?"Suspend":"Reactivate",()=>confirmAction("Change access for "+row.username+"?",()=>perform(row.status==="active"?"suspend":"reactivate"))),
            button("Block temporarily",()=>{const [label,input]=field("Minutes","minutes",60,"number");content.replaceChildren(label,button("Block",async()=>{await perform("block",{minutes:Number(input.value)});dialog.close();}));dialog.showModal();}),
            button("Set daily limit",()=>{const [label,input]=field("Daily requests (blank uses default)","limit",row.daily_limit,"number");content.replaceChildren(label,button("Save limit",async()=>{await perform("limit",{daily_limit:input.value?Number(input.value):null});dialog.close();}));dialog.showModal();}),
            button("Delete",()=>confirmAction("Permanently delete "+row.username+" and their conversations?",()=>perform("delete",{confirmation:row.id}))));
        }
        return [row.username,(accountStatus[row.status] ?? "Unavailable")+" · "+(row.online?"Online":"Offline"),date(row.registered),date(row.last_login),date(row.last_active),row.requests,row.role==="admin"?"Administrator":"Member",actions];
      })));
  }
  search.oninput=draw;status.onchange=draw;draw();
  return [container(label,status),listing];
}
async function sessions() {
  const rows=await data("/admin/sessions");
  return [button("Sign out all members",()=>confirmAction("End every normal user session?",async()=>{await data("/admin/sessions/logout-all",{});await refresh();})),
    table(["Name","Signed in","Last active","Duration","Device or browser","Status","Actions"],rows.map(row=>
    [row.username,date(row.login),date(row.last_active),Math.floor(row.duration_seconds/60)+" min",row.browser,sessionStatus[row.status] ?? "Unavailable",
      container(button("Sign out this device",()=>confirmAction("End this session?",async()=>{await api("/admin/sessions/"+row.id,undefined,"DELETE");await refresh();})),
        button("Sign out all devices",()=>confirmAction("End all sessions for "+row.username+"?",async()=>{await data("/admin/users/"+encodeURIComponent(row.user_id),{action:"logout"});await refresh();}))) ]))];
}
async function analytics(userId="") {
  const [startLabel,start]=field("Start date","start","","date"),[endLabel,end]=field("End date","end","","date");
  const people=await data("/admin/users");
  const userLabel=tag("label","Person");
  const user=select([["","Everyone"],...people.map(person=>[person.id,person.username])]);
  if (people.some(person=>person.id===userId)) user.value=userId;
  userLabel.append(user);
  function query(){return new URLSearchParams({start:start.value,end:end.value,user_id:user.value});}
  const result=tag("section");
  async function draw(){
    const values=await data("/admin/usage?"+query());
    const charts=tag("div");charts.className="charts";
    for (const [title,key] of [["Daily requests","daily"],["Weekly requests","weekly"],["Monthly requests","monthly"],["Busiest hours (server time)","hourly"],["Active users","active_users"],["Document uploads","uploads"],["Most used PDFs","documents"],["Subjects","subjects"],["Modules","modules"]]) charts.append(chart(title,values[key],["daily","weekly","monthly"].includes(key)));
    result.replaceChildren(tag("p",values.total+" requests · "+(values.total-values.failed)+" successful · "+values.failed+" failed · Average "+(values.average_ms===null?"unavailable":(values.average_ms/1000).toFixed(1)+" s")),charts);
  }
  await draw();
  return [container(startLabel,endLabel,userLabel,button("Apply",draw),button("Download report",async()=>{
    const response=await api("/admin/usage?"+query()+"&export=true");
    const url=URL.createObjectURL(await response.blob());const link=tag("a");link.href=url;link.download="usage.csv";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  })),result];
}
async function logs() {
  const [rows,people,files]=await Promise.all([data("/admin/logs"),data("/admin/users"),data("/admin/documents")]);
  const names=new Map(people.map(person=>[person.id,person.username]));
  const titles=new Map(files.map(file=>[file.document_id,file.filename]));
  const actions={
    admin_login:"Signed in",admin_logout:"Signed out",admin_password_changed:"Changed password",
    pdf_uploaded:"Added a PDF",pdf_index_failed:"A PDF couldn’t be prepared",pdf_validation_failed:"A PDF couldn’t be uploaded",
    pdf_replaced:"Replaced a PDF",pdf_deleted:"Removed a PDF",pdf_reprocessed:"Prepared a PDF again",pdf_categories_updated:"Changed PDF categories",
    user_suspend:"Suspended an account",user_reactivate:"Restored account access",user_block:"Temporarily blocked an account",
    user_limit:"Changed a daily limit",user_delete:"Deleted an account",user_logout:"Signed out a member",
    session_revoked:"Signed out a device",normal_sessions_revoked:"Signed out all members",settings_updated:"Updated settings"
  };
  return [table(["When","What happened","Administrator","Item"],rows.map(row=>[
    date(row.at),actions[row.action] ?? "Made a change",names.get(row.actor) ?? "Administrator",
    row.target ? (names.get(row.target) ?? titles.get(row.target) ?? (row.action.startsWith("pdf_") ? "PDF" : "Member")) : "—"
  ]))];
}
async function settings() {
  const config=await data("/admin/settings");
  const keys={max_pdf_mb:"Largest PDF upload (MB)",daily_requests:"Daily questions per person",registrations:"Allow new accounts",maintenance:"Pause the chatbot for maintenance",session_minutes:"Keep people signed in (minutes)"};
  const fields=tag("div");fields.className="fields"; const inputs={};
  for(const [key,title] of Object.entries(keys)){
    const [label,input]=field(title,key,config[key],typeof config[key]==="boolean"?"checkbox":"number");fields.append(label);inputs[key]=input;
  }
  return [fields,button("Save settings",async()=>{
    const values=Object.fromEntries(Object.entries(inputs).map(([key,input])=>[key,input.type==="checkbox"?input.checked:input.type==="number"?(input.value?Number(input.value):null):input.value]));
    await data("/admin/settings",{...config,...values},"PUT");notify("Settings saved.");
  })];
}
async function show(label,userId) {
  active=label;
  const version=++viewVersion;
  for(const entry of nav.children) entry.setAttribute("aria-current",entry.textContent===label?"page":"false");
  const skeleton=tag("div");skeleton.className="skeleton";skeleton.setAttribute("aria-label","Loading");
  root.replaceChildren(tag("h1",label),skeleton);
  const views=[overview,documents,users,sessions,analytics,logs,settings];
  try { const nodes=await views[labels.indexOf(label)](userId);if(version===viewVersion)root.replaceChildren(tag("h1",label),...nodes); }
  catch(error){if(version===viewVersion)root.replaceChildren(tag("h1",label),tag("p",error.message),button("Try again",()=>show(label,userId)));}
}
async function checkSession() {
  const me=await data("/auth/me");
  if(me.role!=="admin"){location.replace("/");return;}
  if(me.password_change_required){
    const [currentLabel,current]=field("Initial password","current","","password");
    const [nextLabel,next]=field("New password (at least 12 characters)","replacement","","password");
    root.replaceChildren(tag("h1","Change your initial password"),currentLabel,nextLabel,button("Change password",async()=>{await api("/admin/password",{current:current.value,replacement:next.value});location.replace("/");}));
    return;
  }
  sidebar.hidden=matchMedia("(max-width:720px)").matches;
  document.querySelector("#menu").setAttribute("aria-expanded",String(!sidebar.hidden));
  for(const label of labels) nav.append(button(label,()=>{if(matchMedia("(max-width:720px)").matches){sidebar.hidden=true;document.querySelector("#menu").setAttribute("aria-expanded","false");}return show(label);}));
  await show("Overview");
  setInterval(()=>data("/auth/me").catch(()=>{}),60000);
}
document.querySelector("#dialog-close").onclick=()=>dialog.close();
dialog.addEventListener("close",()=>{if(previewUrl){URL.revokeObjectURL(previewUrl);previewUrl=undefined;}});
document.querySelector("#menu").onclick=event=>{if(!nav.children.length)return;sidebar.hidden=!sidebar.hidden;event.currentTarget.setAttribute("aria-expanded",String(!sidebar.hidden));};
const savedTheme=localStorage.getItem("perfusion_admin_theme");
document.documentElement.dataset.theme=savedTheme||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");
document.querySelector("#theme").onclick=()=>{const theme=document.documentElement.dataset.theme==="dark"?"light":"dark";document.documentElement.dataset.theme=theme;localStorage.setItem("perfusion_admin_theme",theme);};
document.querySelector("#logout").onclick=async()=>{try{await api("/auth/logout",{});location.replace("/");}catch(error){notify(error.message);}};
checkSession().catch(error=>{root.replaceChildren(tag("p",error.message),button("Try again",checkSession));});
