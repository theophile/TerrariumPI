const $notification=$("#notification"),$btnRefresh=$("#notification .toast-body>button");if("serviceWorker"in navigator){navigator.serviceWorker.register("/TerrariumPI/sw.js").then(t=>{t.waiting&&$notification.toast("show"),t.addEventListener("updatefound",()=>{t.installing.addEventListener("statechange",()=>{t.waiting&&navigator.serviceWorker.controller&&$notification.toast("show")})}),$btnRefresh.click(()=>{t.waiting&&t.waiting.postMessage("SKIP_WAITING"),$notification.toast("hide")})});let t=!1;navigator.serviceWorker.addEventListener("controllerchange",()=>{t||(window.location.reload(),t=!0)})}