// Pais → Sistema → Controles: lista os controles USB, liga/desliga a navegação
// do menu pelo controle e tem um assistente que pede cada botão em sequência.
// O servidor (controles.py) lê o controle e gera a configuração dos jogos.
let controleEstado=null;
let controleAssistente=null; // {chave,nome,evento,passos,indice,mapa,seq,timer}

function controleEl(id){ return document.getElementById(id); }
function controleMensagem(texto,erro){
  const box=controleEl('controleMessage');
  if(!box) return;
  box.hidden=!texto;
  box.textContent=texto||'';
  box.className='ui-state '+(erro?'ui-state-error':'ui-state-success');
}
async function controleApi(caminho,body){
  const opts=body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
  const response=await fetch(caminho,opts);
  const data=await response.json().catch(()=>({}));
  if(!response.ok) throw new Error(data.message||String(response.status));
  return data;
}
async function loadControles(){
  if(!controleEl('controleList')) return;
  renderControleJogos();
  try{
    controleEstado=await controleApi('/api/controles');
    renderControles();
  }catch(e){
    controleMensagem('Não consegui ler os controles ('+e.message+').',true);
  }
}
function renderControles(){
  const list=controleEl('controleList');
  const estado=controleEstado||{dispositivos:[],navegarMenu:true};
  controleEl('controleNavegar').checked=!!estado.navegarMenu;
  list.replaceChildren();
  if(!estado.dispositivos.length){
    const vazio=document.createElement('p');
    vazio.className='muted';
    vazio.textContent='Nenhum controle conectado. Ligue o controle na USB e toque em “Procurar de novo”.';
    list.appendChild(vazio);
    return;
  }
  for(const d of estado.dispositivos){
    const row=document.createElement('div');
    row.className='controle-row';
    const nome=document.createElement('div');
    nome.className='controle-nome';
    nome.textContent='🎮 Jogador '+d.jogador+' — '+(d.nome.trim()||'Controle');
    const info=document.createElement('div');
    info.className='controle-status muted';
    info.textContent=(d.mapa?'✅ Botões configurados':'⚠️ Ainda não configurado (só o direcional funciona no menu)')+' · USB '+d.chave;
    const configurar=document.createElement('button');
    configurar.type='button';
    configurar.className='smallbtn save';
    configurar.textContent=d.mapa?'Configurar de novo':'Configurar botões';
    configurar.onclick=()=>iniciarAssistenteControle(d);
    row.append(nome,info,configurar);
    if(d.mapa){
      const esquecer=document.createElement('button');
      esquecer.type='button';
      esquecer.className='smallbtn';
      esquecer.textContent='Apagar configuração';
      esquecer.onclick=async()=>{
        try{ controleEstado=await controleApi('/api/controles/esquecer',{chave:d.chave}); renderControles(); controleMensagem('Configuração apagada.'); }
        catch(e){ controleMensagem('Não consegui apagar ('+e.message+').',true); }
      };
      row.appendChild(esquecer);
    }
    list.appendChild(row);
  }
}
async function definirNavegacaoControle(ligada){
  try{
    controleEstado=await controleApi('/api/controles/navegacao',{ligada:ligada});
    controleMensagem(ligada?'O controle navega no menu.':'O controle não mexe mais no menu.');
  }catch(e){
    controleMensagem('Não consegui salvar ('+e.message+').',true);
  }
}
async function iniciarAssistenteControle(d){
  if(controleAssistente) await pararAssistenteControle();
  const passos=(controleEstado&&controleEstado.botoes)||[];
  controleAssistente={chave:d.chave,nome:d.nome,evento:d.evento,passos:passos,indice:0,mapa:{},seq:0,timer:null};
  controleMensagem('');
  try{ await controleApi('/api/controles/captura',{acao:'iniciar'}); }
  catch(e){ controleMensagem('Não consegui começar ('+e.message+').',true); controleAssistente=null; return; }
  controleEl('controleWizard').hidden=false;
  renderPassoControle('');
  esperarBotaoControle();
}
function renderPassoControle(aviso){
  const a=controleAssistente;
  if(!a) return;
  const passo=a.passos[a.indice];
  controleEl('controleWizardDevice').textContent='Jogador com o controle “'+(a.nome.trim()||'Controle')+'”';
  controleEl('controleWizardStep').textContent='Passo '+(a.indice+1)+' de '+a.passos.length;
  controleEl('controleWizardPrompt').textContent=passo?passo.texto:'';
  controleEl('controleWizardHint').textContent=aviso||(passo&&passo.obrigatorio?'Aperte e solte.':'Aperte e solte, ou toque em “Pular” se o controle não tiver.');
  controleEl('controleWizardSkip').hidden=!passo||passo.obrigatorio;
  controleEl('controleWizardBack').disabled=a.indice===0;
}
function esperarBotaoControle(){
  const a=controleAssistente;
  if(!a) return;
  const panel=controleEl('controlePanel');
  if(!panel||panel.offsetParent===null){ pararAssistenteControle(); return; }
  a.timer=setTimeout(async()=>{
    if(controleAssistente!==a) return;
    try{
      const data=await controleApi('/api/controles/captura?depois='+a.seq);
      const c=data.captura;
      if(c&&controleAssistente===a){
        a.seq=c.seq;
        if(c.evento===a.evento) receberBotaoControle(c.token);
      }
    }catch(e){ /* tenta de novo */ }
    esperarBotaoControle();
  },150);
}
function receberBotaoControle(token){
  const a=controleAssistente;
  const passo=a.passos[a.indice];
  if(!passo) return;
  const analogico=['lx','ly','rx','ry'].includes(passo.id);
  const eixo=/^a:(\d+):/.exec(token);
  const ehHat=eixo&&Number(eixo[1])>=16&&Number(eixo[1])<=23;
  if(analogico&&(!eixo||ehHat)){ renderPassoControle('Use o analógico (a alavanca), não um botão.'); return; }
  // o mesmo eixo pode ser direcional e analógico (controle com o modo analógico desligado)
  const ANALOGICOS=['lx','ly','rx','ry'];
  const usado=Object.entries(a.mapa).find(([id,t])=>analogico
    ?ANALOGICOS.includes(id)&&t.startsWith('a:'+eixo[1]+':')
    :!ANALOGICOS.includes(id)&&t===token);
  if(usado){
    const nome=(a.passos.find(p=>p.id===usado[0])||{}).texto||usado[0];
    renderPassoControle('Esse já foi usado em: '+nome+'. Aperte outro.');
    return;
  }
  a.mapa[passo.id]=token;
  avancarPassoControle();
}
function avancarPassoControle(){
  const a=controleAssistente;
  a.indice++;
  if(a.indice>=a.passos.length){ concluirAssistenteControle(); return; }
  renderPassoControle('');
}
function pularPassoControle(){
  const a=controleAssistente;
  if(!a) return;
  delete a.mapa[a.passos[a.indice].id];
  avancarPassoControle();
}
function voltarPassoControle(){
  const a=controleAssistente;
  if(!a||a.indice===0) return;
  a.indice--;
  delete a.mapa[a.passos[a.indice].id];
  renderPassoControle('');
}
async function concluirAssistenteControle(){
  const a=controleAssistente;
  try{
    controleEstado=await controleApi('/api/controles/salvar',{chave:a.chave,nome:a.nome,mapa:a.mapa});
    controleMensagem('Pronto! Os botões valem para o menu, Super Nintendo, PlayStation e jogos como SuperTux e SuperTuxKart.');
  }catch(e){
    controleMensagem('Não consegui salvar ('+e.message+').',true);
  }
  await pararAssistenteControle();
  renderControles();
}
async function pararAssistenteControle(){
  const a=controleAssistente;
  controleAssistente=null;
  if(a&&a.timer) clearTimeout(a.timer);
  const wizard=controleEl('controleWizard');
  if(wizard) wizard.hidden=true;
  try{ await controleApi('/api/controles/captura',{acao:'parar'}); }catch(e){ /* expira sozinha */ }
}

// Selo 🎮 nos tiles (tile.gamepad), salvo junto com o resto pelo botão Salvar
function renderControleJogos(){
  const lista=controleEl('controleJogos');
  if(!lista||typeof cfg!=='object'||!cfg||!Array.isArray(cfg.tiles)) return;
  lista.replaceChildren();
  for(const tile of cfg.tiles){
    if(!tile.visible) continue;
    const item=document.createElement('label');
    item.className='chk controle-jogo';
    const caixa=document.createElement('input');
    caixa.type='checkbox';
    caixa.checked=tile.gamepad===true;
    caixa.onchange=()=>{ if(caixa.checked) tile.gamepad=true; else delete tile.gamepad; };
    const nome=document.createElement('span');
    const emoji=typeof emojiComoTexto==='function'?emojiComoTexto(tile.emoji):'';
    nome.textContent=(emoji?emoji+' ':'')+(tile.label||tile.id);
    item.append(caixa,nome);
    lista.appendChild(item);
  }
}
