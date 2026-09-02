const CACHE_NAME = "socialpilot-app-shell-v1";
const APP_SHELL = "/";

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.add(APP_SHELL))
      .catch(() => undefined),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names
          .filter((name) => name.startsWith("socialpilot-app-shell-") && name !== CACHE_NAME)
          .map((name) => caches.delete(name)),
      ))
      .then(() => self.clients.claim()),
  );
});

function fetchWithTimeout(request, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(request, { signal: controller.signal })
    .finally(() => clearTimeout(timer));
}

async function remember(cacheKey, response) {
  if (response.ok && response.type === "basic") {
    const cache = await caches.open(CACHE_NAME);
    await cache.put(cacheKey, response.clone());
  }
  return response;
}

async function navigationResponse(request) {
  try {
    const response = await fetchWithTimeout(request, 5_000);
    await remember(APP_SHELL, response);
    return response;
  } catch {
    return (await caches.match(request))
      || (await caches.match(APP_SHELL))
      || new Response(
        "<!doctype html><meta charset='utf-8'><title>SocialPilot AI</title>"
          + "<main style='font-family:sans-serif;padding:40px'>"
          + "<h1>网络暂时中断</h1><p>请等待网络恢复后刷新页面。为避免重复操作，请勿连续提交。</p></main>",
        { headers: { "Content-Type": "text/html; charset=utf-8" }, status: 503 },
      );
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;

  // Never cache authentication, API responses, user data, generated media or uploads.
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(navigationResponse(request));
    return;
  }

  if (["script", "style", "font"].includes(request.destination)) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request).then(
        (response) => remember(request, response),
      )),
    );
  }
});
