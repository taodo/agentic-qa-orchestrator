// Appearance only. Same-origin classic script runs before the SPA without inline-CSP exceptions.
try{document.documentElement.dataset.theme=localStorage.getItem("qa-sentinel.theme")==="light"?"light":"dark"}catch{document.documentElement.dataset.theme="dark"}
