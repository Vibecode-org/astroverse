// Chrome MCP press_key has no hold duration. Supplement it with trusted CDP
// keyboard input over the same Chrome target; no application state mutation.
const [base,code,durationText]=process.argv.slice(2);
const targets=await (await fetch(base+'/json/list')).json();
const target=targets.find(t=>t.type==='page'&&t.url.startsWith('http://localhost:'));
if(!target)throw new Error('Chrome page missing');
const ws=new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
let next=0;const pending=new Map();
ws.onmessage=event=>{const value=JSON.parse(event.data);const entry=pending.get(value.id);if(entry){pending.delete(value.id);value.error?entry.reject(value.error):entry.resolve(value.result);}};
const send=(method,params)=>new Promise((resolve,reject)=>{const id=++next;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
if(code==='Click'){
 const [x,y]=JSON.parse(durationText);
 await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,x,y});
 await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,x,y});ws.close();
}else if(code==='Wheel'){
 const [x,y]=JSON.parse(durationText);
 await send('Input.dispatchMouseEvent',{type:'mouseWheel',x,y,deltaX:0,deltaY:1000});ws.close();
}else if(code==='Drag'){
 const [x,y]=JSON.parse(durationText);
 await send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y});
 await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,x,y});
 try{
  for(let i=1;i<=8;i++){
   await send('Input.dispatchMouseEvent',{type:'mouseMoved',buttons:1,x:x+i*8,y:y+i*3});
   await new Promise(resolve=>setTimeout(resolve,20));
  }
 }finally{await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,x:x+64,y:y+24});ws.close();}
}else if(code==='Read'){
 // Chrome MCP emulates focus even for background tabs. Disable that override
 // before observing actual browser visibility (no document-property mocks).
 await send('Emulation.setFocusEmulationEnabled',{enabled:false});
 const result=await send('Runtime.evaluate',{expression:`(()=>{const s=window.__sectorStage,c=s.camera.position,o=s.reference?s.reference.position.map((v,a)=>v+s.reference.offset[a]):s.layer.inspect().origin;
 return {hidden:document.hidden,held:s.flight.inspect().held,eye:[o[0]+c.x*1e5,o[1]-c.z*1e5,o[2]+c.y*1e5]};})()`,returnByValue:true});
 console.log(JSON.stringify(result.result.value));ws.close();
}else{
const key=code.startsWith('Key')?code.slice(3).toLowerCase():code;
const virtual=code.startsWith('Key')?code.charCodeAt(3):{ArrowLeft:37,ArrowUp:38,ArrowRight:39,ArrowDown:40,Space:32}[code];
const event={key,code,windowsVirtualKeyCode:virtual,nativeVirtualKeyCode:virtual};
try{
 await send('Input.dispatchKeyEvent',{...event,type:'keyDown'});
 await new Promise(resolve=>setTimeout(resolve,Number(durationText)));
}finally{
 await send('Input.dispatchKeyEvent',{...event,type:'keyUp'});ws.close();
}
}
