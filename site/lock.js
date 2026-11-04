/* GPS Watch - password lock (decrypts the dashboard data in the browser) */
window.GPSLock = (() => {
  const KEY = "gpswatch-pw";
  const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));

  async function decrypt(env, pw) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]);
    const key = await crypto.subtle.deriveKey(
      { name: "PBKDF2", salt: b64(env.salt), iterations: env.iter, hash: "SHA-256" },
      base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(env.iv) }, key, b64(env.ct));
    return new TextDecoder().decode(pt);
  }
  const tryOpen = async (env, pw) => { try { return await decrypt(env, pw); } catch (e) { return null; } };

  const stored = () => { try { return sessionStorage.getItem(KEY) || localStorage.getItem(KEY) || ""; } catch (e) { return ""; } };
  const save = (pw, remember) => { try { sessionStorage.setItem(KEY, pw); if (remember) localStorage.setItem(KEY, pw); else localStorage.removeItem(KEY); } catch (e) {} };
  const forget = () => { try { sessionStorage.removeItem(KEY); localStorage.removeItem(KEY); } catch (e) {} };
  const current = () => { try { return sessionStorage.getItem(KEY) || ""; } catch (e) { return ""; } };

  const css = `
  .gate { position:fixed; inset:0; z-index:5000; display:flex; align-items:center; justify-content:center; padding:16px;
          background:#0e1319; font-family:"Segoe UI",Arial,sans-serif; color:#e8edf2; }
  .gate form { width:100%; max-width:360px; background:#161d26; border:1px solid #263241; border-radius:12px; padding:26px 24px; }
  .gate .ic { width:42px; height:42px; border-radius:50%; background:#12283a; display:flex; align-items:center; justify-content:center; margin-bottom:14px; }
  .gate h1 { font-size:18px; margin:0 0 4px; } .gate p { margin:0 0 18px; color:#93a1b1; font-size:13px; }
  .gate input[type=password] { width:100%; box-sizing:border-box; background:#0f151c; color:#e8edf2; border:1px solid #263241; border-radius:6px; padding:10px 12px; font:inherit; font-size:15px; }
  .gate input[type=password]:focus { outline:2px solid #4aa3df; outline-offset:1px; }
  .gate label.rm { display:flex; gap:8px; align-items:center; font-size:13px; color:#93a1b1; margin:12px 0 0; cursor:pointer; }
  .gate button { margin-top:16px; width:100%; background:#4aa3df; color:#06121d; border:0; border-radius:6px; padding:11px; font:inherit; font-weight:700; cursor:pointer; }
  .gate button:disabled { opacity:.6; cursor:wait; }
  .gate .err { color:#ff8a7a; font-size:13px; min-height:18px; margin-top:10px; }`;

  /** Returns {text, pw}. Uses the saved password if it still works, otherwise shows the lock screen. */
  async function unlock(env, title) {
    const pw0 = stored();
    if (pw0) { const t = await tryOpen(env, pw0); if (t != null) { try { sessionStorage.setItem(KEY, pw0); } catch (e) {} return { text: t, pw: pw0 }; } }
    return new Promise(resolve => {
      const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
      const g = document.createElement("div"); g.className = "gate";
      g.innerHTML = `<form autocomplete="off">
        <div class="ic"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4aa3df" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg></div>
        <h1></h1><p>Enter the password to open.</p>
        <input type="password" placeholder="Password" required>
        <label class="rm"><input type="checkbox"> Remember on this computer</label>
        <button type="submit">Unlock</button><div class="err"></div></form>`;
      g.querySelector("h1").textContent = title || "GPS Interference Watch";
      document.body.appendChild(g);
      const inp = g.querySelector("input[type=password]"), btn = g.querySelector("button"), err = g.querySelector(".err");
      inp.focus();
      g.querySelector("form").addEventListener("submit", async ev => {
        ev.preventDefault();
        btn.disabled = true; btn.textContent = "Checking…"; err.textContent = "";
        const pw = inp.value;
        const t = await tryOpen(env, pw);
        btn.disabled = false; btn.textContent = "Unlock";
        if (t == null) { err.textContent = "Wrong password."; inp.select(); return; }
        save(pw, g.querySelector(".rm input").checked);
        g.remove(); st.remove();
        resolve({ text: t, pw });
      });
    });
  }

  return { unlock, forget, current };
})();
