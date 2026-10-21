/* Light / Dark switch shown at the top right of every page.
   Loaded in <head>: applies the saved choice before the page paints (no flash), then adds the switch.
   Without a saved choice the page follows the device setting. Pages must define their colour tokens for
   :root[data-theme="light"|"dark"] (see CLAUDE.md). */
(function(){
  var KEY='icse10-theme', root=document.documentElement;
  function stored(){try{var v=localStorage.getItem(KEY);return v==='light'||v==='dark'?v:null}catch(e){return null}}
  function systemDark(){return !!(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches)}
  function effective(){return root.getAttribute('data-theme')||(systemDark()?'dark':'light')}
  var saved=stored();
  if(saved)root.setAttribute('data-theme',saved);

  var css='.theme-switch{position:absolute;top:max(10px,env(safe-area-inset-top,0px));right:max(16px,env(safe-area-inset-right,0px));z-index:50;display:flex;'
    +'border:1px solid var(--line,#d3dce6);border-radius:10px;overflow:hidden;background:var(--panel,#fff)}'
    +'.theme-switch button{font:600 14px/1 var(--font-body,system-ui,sans-serif);min-height:44px;min-width:64px;padding:0 14px;border:0;border-radius:0;'
    +'background:transparent;color:var(--fg,#14202e);cursor:pointer}'
    +'.theme-switch button[aria-pressed="true"]{background:var(--fg,#14202e);color:var(--bg,#fff)}'
    +'.theme-switch button:focus-visible{outline:3px solid var(--accent,#1d4ed8);outline-offset:-3px}'
    +'html body{padding-top:max(64px,calc(env(safe-area-inset-top,0px) + 64px))}';

  function build(){
    var st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
    var box=document.createElement('nav');
    box.className='theme-switch';box.setAttribute('aria-label','Colour theme');
    var btns={};
    ['light','dark'].forEach(function(mode){
      var b=document.createElement('button');b.type='button';b.textContent=mode==='light'?'Light':'Dark';
      b.addEventListener('click',function(){
        root.setAttribute('data-theme',mode);
        try{localStorage.setItem(KEY,mode)}catch(e){}
        sync();
      });
      btns[mode]=b;box.appendChild(b);
    });
    function sync(){var cur=effective();for(var m in btns)btns[m].setAttribute('aria-pressed',String(m===cur))}
    sync();
    if(window.matchMedia)try{matchMedia('(prefers-color-scheme: dark)').addEventListener('change',sync)}catch(e){}
    document.body.insertBefore(box,document.body.firstChild);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',build);else build();
})();
