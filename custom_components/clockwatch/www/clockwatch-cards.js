/* Clockwatch cards: the charge receipt, the trip receipt and the month, each with a choice of style.
 * Served and loaded by the Clockwatch integration; add them from the dashboard's card picker.
 * They read the Clockwatch sensors (last charge, last trip, this month) and, for older receipts and the month's weeks, the clockwatch.history
 * action. Nothing is fetched from outside Home Assistant. */
(() => {
  const VERSION = "0.2.0";
  const DOMAIN = "clockwatch";
  const SUN = "#F5B700", BATT = "#2EB872", GRID = "#8796A3";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const KM = 1.609344;

  // ------------------------------------------------------------------ shared helpers
  function findEntity(hass, suffix) {
    const ids = Object.keys(hass.states).filter((id) => id.startsWith("sensor.") && id.endsWith(suffix));
    const ours = ids.filter((id) => (hass.entities && hass.entities[id] ? hass.entities[id].platform === DOMAIN : id.startsWith("sensor.clockwatch")));
    return ours[0] || null;
  }

  function fmt(hass, config) {
    const currency = (hass.config && hass.config.currency) || "GBP";
    const unitsCfg = config.units || "auto";
    const miles = unitsCfg === "mi" ? true : unitsCfg === "km" ? false : !!(hass.config && hass.config.unit_system && hass.config.unit_system.length === "mi");
    const lang = (hass.locale && hass.locale.language) || hass.language || "en-GB";
    const money = (v) => {
      if (v == null || isNaN(v)) return "–";
      if (currency === "GBP" && Math.abs(v) < 1) return `${Math.round(v * 100)}p`;
      try {
        return new Intl.NumberFormat(lang, { style: "currency", currency, maximumFractionDigits: 2 }).format(v);
      } catch (e) {
        return `${v.toFixed(2)} ${currency}`;
      }
    };
    const perDist = (v) => {
      if (v == null) return "–";
      const per = miles ? v : v / KM;
      if (currency === "GBP") return `${(per * 100).toFixed(1)}p/${miles ? "mi" : "km"}`;
      return `${money(per)}/${miles ? "mi" : "km"}`;
    };
    const dist = (mi, dp = 1) => (mi == null ? "–" : miles ? `${(+mi).toFixed(dp)} mi` : `${(mi * KM).toFixed(dp)} km`);
    const speed = (mph) => (mph == null ? "–" : miles ? `${Math.round(mph)}` : `${Math.round(mph * KM)}`);
    const speedUnit = miles ? "mph" : "km/h";
    const eff = (mpk) => (mpk == null ? "–" : miles ? `${(+mpk).toFixed(1)} mi/kWh` : `${(mpk * KM).toFixed(1)} km/kWh`);
    const kwh = (v, dp = 1) => (v == null ? "–" : `${(+v).toFixed(dp)} kWh`);
    const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
    const time = (iso) => {
      if (!iso) return "";
      const d = new Date(iso);
      return d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
    };
    const day = (iso) => {
      if (!iso) return "";
      const d = new Date(iso);
      return d.toLocaleDateString(lang, { weekday: "short", day: "numeric", month: "short" });
    };
    const dur = (min) => {
      if (min == null) return "";
      const h = Math.floor(min / 60), m = Math.round(min % 60);
      return h ? `${h} h ${m} min` : `${m} min`;
    };
    return { money, perDist, dist, speed, speedUnit, eff, kwh, pct, time, day, dur, miles, currency };
  }

  async function history(hass, config, kind, month) {
    const data = { kind, limit: 60 };
    if (month) data.month = month;
    if (config.config_entry_id) data.config_entry_id = config.config_entry_id;
    const r = await hass.connection.sendMessagePromise({ type: "call_service", domain: DOMAIN, service: "history", service_data: data, return_response: true });
    return r && r.response;
  }

  const BASE = `
    :host{display:block}
    ha-card{overflow:hidden}
    .pad{padding:16px}
    .muted{color:var(--secondary-text-color)}
    .empty{padding:20px 16px;color:var(--secondary-text-color);font-size:14px}
    .nav{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 10px;border-top:1px solid var(--divider-color);font-size:12px;color:var(--secondary-text-color)}
    .nav button{border:0;background:transparent;color:var(--primary-color);font:inherit;font-size:18px;line-height:1;padding:4px 10px;border-radius:8px;cursor:pointer}
    .nav button[disabled]{opacity:.3;cursor:default}
    .nav button:focus-visible{outline:2px solid var(--primary-color)}
    .sw{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:0}
    .chips{display:flex;flex-wrap:wrap;gap:8px}
    .chip{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:999px;background:var(--secondary-background-color);font-size:13px;color:var(--primary-text-color)}
    .chip b{font-weight:500}
  `;

  class Base extends HTMLElement {
    setConfig(config) {
      this._config = { ...config };
      this._idx = 0;
      this._list = null;
      if (!this.shadowRoot) {
        this.attachShadow({ mode: "open" });
        this.shadowRoot.addEventListener("click", (e) => {
          const b = e.target.closest("button[data-nav]");
          if (b) this._nav(+b.dataset.nav);
        });
      }
      this._render();
    }
    set hass(hass) {
      this._hass = hass;
      const id = this._entityId();
      const st = id && hass.states[id];
      const key = st ? st.last_updated + "|" + (hass.config.unit_system || {}).length : "none";
      if (key !== this._key) {
        this._key = key;
        this._list = null;
        this._idx = 0;
        this._render();
      }
    }
    getCardSize() {
      return 5;
    }
    getGridOptions() {
      return { columns: 12, min_columns: 6, rows: "auto" };
    }
    _entityId() {
      return this._config.entity || (this._hass && findEntity(this._hass, this.constructor.SUFFIX));
    }
    _receipt() {
      if (this._idx > 0 && this._list) return this._list[this._idx];
      const id = this._entityId();
      const st = id && this._hass && this._hass.states[id];
      return st && st.attributes && st.attributes.ended ? st.attributes : null;
    }
    async _nav(step) {
      if (!this._list) {
        try {
          const r = await history(this._hass, this._config, this.constructor.KIND);
          this._list = (r && r[this.constructor.KIND]) || [];
        } catch (e) {
          this._list = [];
        }
      }
      this._idx = Math.max(0, Math.min(this._list.length - 1, this._idx + step));
      this._render();
    }
    _navBar() {
      const n = this._list ? this._list.length : null;
      return `<div class="nav"><button data-nav="1" aria-label="Older" ${n != null && this._idx >= n - 1 ? "disabled" : ""}>‹</button>
        <span>${this._idx === 0 ? "Latest" : `${this._idx + 1} of ${n}`}</span>
        <button data-nav="-1" aria-label="Newer" ${this._idx === 0 ? "disabled" : ""}>›</button></div>`;
    }
    _render() {
      if (!this.shadowRoot || !this._hass || !this._config) return;
      const r = this._receipt();
      const f = fmt(this._hass, this._config);
      const style = this._config.style || this.constructor.DEFAULT_STYLE;
      const body = r ? this.draw(style, r, f) : `<div class="empty">${esc(this.constructor.EMPTY)}</div>`;
      this.shadowRoot.innerHTML = `<style>${BASE}${this.constructor.STYLE}</style><ha-card>${body}${r ? this._navBar() : ""}</ha-card>`;
    }
  }

  // ------------------------------------------------------------------ charge card
  const CHARGE_STYLE = `
    .classic{color:#fff;background:linear-gradient(150deg,#1AA6A0,#3CC7B6);padding:18px 18px 14px;display:flex;flex-direction:column;gap:12px}
    .classic.night{background:linear-gradient(150deg,#3949AB,#5C6BC0)}
    .classic .t{font-weight:500;font-size:14.5px}.classic .t span{opacity:.85;font-weight:400}
    .classic .big{font-size:38px;font-weight:700;letter-spacing:-.02em;line-height:1}
    .mix{display:flex;height:12px;border-radius:6px;overflow:hidden;background:rgba(255,255,255,.25)}
    .mix i{display:block;height:100%}
    .legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12.5px}
    .classic .sw{box-shadow:0 0 0 1.5px rgba(255,255,255,.85)}
    .tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
    .tile{background:rgba(255,255,255,.16);border-radius:12px;padding:10px 12px}
    .tile b{display:block;font-size:18px;font-weight:700}.tile small{font-size:11.5px;opacity:.9}
    .foot{font-size:11.5px;opacity:.85}
    .pump{background:#16191C;color:#E8F7EE;padding:16px}
    .pump .top{display:flex;justify-content:space-between;font:500 12px var(--paper-font-body1_-_font-family,Roboto,sans-serif);letter-spacing:.12em;text-transform:uppercase;color:#9FB3A8}
    .pump .top i{color:#7CF2A4;font-style:normal}
    .lcd{margin-top:10px;background:#0B1F14;border-radius:10px;padding:10px 14px;border:1px solid #1D3A2A;box-shadow:inset 0 2px 8px rgba(0,0,0,.6)}
    .lcd .r{display:flex;justify-content:space-between;align-items:baseline;padding:4px 0;border-bottom:1px solid rgba(124,242,164,.12)}
    .lcd .r:last-child{border-bottom:0}
    .lcd .l{font-size:11px;letter-spacing:.14em;color:#6FA488;text-transform:uppercase}
    .lcd .v{font-family:"Share Tech Mono","Courier New",ui-monospace,monospace;font-size:34px;line-height:1;color:#7CF2A4;text-shadow:0 0 8px rgba(124,242,164,.45)}
    .lcd .v.sm{font-size:24px}
    .nozzle{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
    .nz{border-radius:10px;padding:8px 10px;text-align:center;font-size:11px;letter-spacing:.08em;text-transform:uppercase}
    .nz b{display:block;font-size:22px;font-weight:700;letter-spacing:0}
    .nz.s{background:#3A2F07;color:#FFD34D}.nz.b{background:#0D3320;color:#6EE29E}.nz.g{background:#242A2F;color:#B5C2CC}
    .pump .ft{margin-top:10px;font-size:11.5px;color:#8FA59A}
    .mini .hd{display:flex;align-items:center;gap:12px}
    .mini .ico{flex:none;width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:rgba(var(--rgb-primary-color,3,169,244),.12);color:var(--primary-color);--mdc-icon-size:22px}
    .mini .hd b{display:block;font-weight:500;font-size:15px;color:var(--primary-text-color)}
    .mini .hd small{font-size:12.5px;color:var(--secondary-text-color)}
    .mini .amt{margin-left:auto;text-align:right}.mini .amt b{font-size:20px;font-weight:700}
    .thin{display:flex;height:6px;border-radius:3px;overflow:hidden;margin:14px 0;background:var(--divider-color)}
    .thin i{display:block}
    .curve .hd{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
    .curve .hd b{font-size:15px;font-weight:500;color:var(--primary-text-color)}
    .curve svg{display:block;width:100%;height:auto;margin-top:6px}
    .axis{font-size:10.5px;fill:var(--secondary-text-color)}
    .gridl{stroke:var(--divider-color);stroke-width:1}
    .curve .legend{color:var(--primary-text-color);margin-top:4px}
    .stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:12px;border-top:1px solid var(--divider-color);padding-top:10px}
    .stats b{display:block;font-size:16px;font-weight:700;color:var(--primary-text-color)}.stats small{font-size:11.5px;color:var(--secondary-text-color)}
    @media (max-width:420px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
  `;

  function mixBar(r, cls) {
    return `<div class="${cls}" role="img" aria-label="${Math.round(r.solar_share * 100)}% solar, ${Math.round(r.battery_share * 100)}% home battery, ${Math.round(r.grid_share * 100)}% grid">
      <i style="width:${r.solar_share * 100}%;background:${SUN}"></i><i style="width:${r.battery_share * 100}%;background:${BATT}"></i><i style="width:${r.grid_share * 100}%;background:${GRID}"></i></div>`;
  }

  function curveSvg(r, f) {
    const pts = (r.curve || []).filter((p) => p && p.length >= 4);
    if (pts.length < 2) return `<div class="muted" style="padding:20px 0;font-size:13px">No charging curve for this charge.</div>`;
    const W = 320, H = 130, x0 = 30, x1 = 314, y0 = 100, yTop = 18;
    const maxM = Math.max(...pts.map((p) => p[0])) || 1;
    const maxKw = Math.max(1, Math.ceil(Math.max(...pts.map((p) => p[1]))));
    const X = (m) => x0 + (m / maxM) * (x1 - x0);
    const Y = (kw) => y0 - (kw / maxKw) * (y0 - yTop);
    const band = (lo, hi) => {
      const top = pts.map((p) => `${X(p[0]).toFixed(1)},${Y(hi(p)).toFixed(1)}`);
      const bot = pts.slice().reverse().map((p) => `${X(p[0]).toFixed(1)},${Y(lo(p)).toFixed(1)}`);
      return `M${top.join(" L")} L${bot.join(" L")} Z`;
    };
    const solar = (p) => p[1] * p[2], batt = (p) => p[1] * (p[2] + p[3]), all = (p) => p[1];
    const start = new Date(r.started), mid = new Date(start.getTime() + (maxM / 2) * 60000);
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Charging power over time, coloured by where the energy came from">
      <line class="gridl" x1="${x0}" y1="${yTop}" x2="${x1}" y2="${yTop}"/><line class="gridl" x1="${x0}" y1="${(y0 + yTop) / 2}" x2="${x1}" y2="${(y0 + yTop) / 2}"/>
      <text class="axis" x="${x0 - 4}" y="${yTop + 4}" text-anchor="end">${maxKw} kW</text><text class="axis" x="${x0 - 4}" y="${y0 + 4}" text-anchor="end">0</text>
      <path d="${band(() => 0, solar)}" fill="${SUN}" opacity=".9"/>
      <path d="${band(solar, batt)}" fill="${BATT}" opacity=".95"/>
      <path d="${band(batt, all)}" fill="${GRID}" opacity=".85"/>
      <line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y0}" stroke="var(--secondary-text-color)" stroke-width="1"/>
      <text class="axis" x="${x0}" y="${y0 + 18}">${esc(f.time(r.started))}</text>
      <text class="axis" x="${(x0 + x1) / 2}" y="${y0 + 18}" text-anchor="middle">${esc(f.time(mid.toISOString()))}</text>
      <text class="axis" x="${x1}" y="${y0 + 18}" text-anchor="end">${esc(f.time(r.ended))}</text></svg>`;
  }

  class ChargeCard extends Base {
    static SUFFIX = "_last_charge";
    static KIND = "charges";
    static DEFAULT_STYLE = "curve";
    static EMPTY = "No charges yet. The first receipt appears when the next charge finishes.";
    static STYLE = CHARGE_STYLE;
    static getConfigElement() {
      return document.createElement("clockwatch-card-editor").withStyles("charge");
    }
    static getStubConfig() {
      return { style: "curve" };
    }
    draw(style, r, f) {
      const minutes = (new Date(r.ended) - new Date(r.started)) / 60000;
      const when = `${f.day(r.started)} · ${f.time(r.started)}–${f.time(r.ended)}`;
      const soc = r.soc_start != null && r.soc_end != null ? `${Math.round(r.soc_start)} → ${Math.round(r.soc_end)} %` : "";
      const added = r.miles_added != null ? `≈ ${f.dist(r.miles_added, 0)}` : "–";
      const src = [["Solar", r.energy.solar, SUN], ["Home battery", r.energy.battery, BATT], ["Grid", r.energy.grid, GRID]];
      if (style === "pump") {
        return `<div class="pump"><div class="top"><span>Clockwatch</span><i>● Charge complete</i></div>
          <div class="lcd"><div class="r"><span class="l">Sale</span><span class="v">${esc(f.money(r.cost))}</span></div>
          <div class="r"><span class="l">kWh</span><span class="v">${(+r.kwh).toFixed(2)}</span></div>
          <div class="r"><span class="l">Per ${f.miles ? "mile" : "km"}</span><span class="v sm">${esc(f.perDist(r.cost_per_mile))}</span></div></div>
          <div class="nozzle"><div class="nz s">Solar<b>${(+r.energy.solar).toFixed(1)}</b></div><div class="nz b">Battery<b>${(+r.energy.battery).toFixed(1)}</b></div><div class="nz g">Grid<b>${(+r.energy.grid).toFixed(1)}</b></div></div>
          <div class="ft">${esc(when)}${soc ? " · " + soc : ""} · ${esc(added)} added</div></div>`;
      }
      if (style === "minimal") {
        return `<div class="pad mini"><div class="hd"><span class="ico"><ha-icon icon="mdi:ev-station"></ha-icon></span>
          <div><b>Charged ${esc(f.kwh(r.kwh))}</b><small>${esc(when)}${soc ? " · " + soc : ""}</small></div>
          <div class="amt"><b>${esc(f.money(r.cost))}</b><small class="muted" style="display:block;font-size:12px">${esc(f.perDist(r.cost_per_mile))}</small></div></div>
          ${mixBar(r, "thin")}
          <div class="chips">${src.filter((s) => s[1] > 0.05).map((s) => `<span class="chip"><i class="sw" style="background:${s[2]}"></i><b>${Math.round((s[1] / r.kwh) * 100)}%</b> ${s[0].toLowerCase()}</span>`).join("")}
          <span class="chip">${esc(added)} added</span></div></div>`;
      }
      if (style === "classic") {
        const night = r.solar_share < 0.05 && r.battery_share < 0.05;
        return `<div class="classic ${night ? "night" : ""}"><div class="t">${night ? "🌙" : "⚡"} Last charge <span>· ${esc(when)} · ${esc(f.dur(minutes))}</span></div>
          <div class="big">+${(+r.kwh).toFixed(1)} kWh</div>${soc ? `<div>🔋 ${soc}</div>` : ""}
          ${mixBar(r, "mix")}
          <div class="legend">${src.map((s) => `<span><i class="sw" style="background:${s[2]}"></i>${s[0]} <b>${(+s[1]).toFixed(1)} kWh</b></span>`).join("")}</div>
          <div class="tiles"><div class="tile"><b>${esc(f.money(r.cost))}</b><small>cost of this charge</small></div><div class="tile"><b>${esc(added)}</b><small>range added</small></div>
          <div class="tile"><b>${esc(f.perDist(r.cost_per_mile))}</b><small>cost per ${f.miles ? "mile" : "km"}</small></div></div>
          ${r.energy.solar > 0.05 ? `<div class="foot">Solar counted at the export price you gave up. Counted as free: ${esc(f.money(r.cost_if_solar_free))}.</div>` : ""}</div>`;
      }
      // curve (default)
      return `<div class="pad curve"><div class="hd"><b>Charge · ${esc(f.kwh(r.kwh))}</b><small class="muted">${esc(when)}</small></div>
        ${curveSvg(r, f)}
        <div class="legend">${src.filter((s) => s[1] > 0.05).map((s) => `<span><i class="sw" style="background:${s[2]}"></i>${s[0]} ${(+s[1]).toFixed(1)} kWh</span>`).join("")}</div>
        <div class="stats"><div><b>${esc(f.money(r.cost))}</b><small>cost</small></div><div><b>${esc(f.perDist(r.cost_per_mile))}</b><small>per ${f.miles ? "mile" : "km"}</small></div>
        <div><b>${esc(added)}</b><small>added</small></div><div><b>${esc(f.pct(r.solar_share))}</b><small>solar</small></div></div></div>`;
    }
  }

  // ------------------------------------------------------------------ trip card
  const TRIP_STYLE = `
    .paper{position:relative;background:#FFFDF6;color:#2A2A2A;font-family:"Courier Prime","Courier New",ui-monospace,monospace;padding:18px 20px 20px}
    .paper h3{margin:0;font:700 18px var(--paper-font-body1_-_font-family,Roboto,sans-serif)}
    .paper .when{font-size:12.5px;opacity:.75;margin-top:2px}
    .phd{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
    .stamp{flex:none;margin-top:2px;transform:rotate(-6deg);border:2.5px solid #2E9E5B;color:#2E9E5B;border-radius:10px;padding:3px 9px;font:700 11.5px Roboto,sans-serif;letter-spacing:.06em}
    .lines{margin:14px 0 0;border-top:1px dashed #D9D3C2}
    .ln{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed #D9D3C2;font-size:14px}
    .total{display:flex;justify-content:space-between;padding:10px 0 6px;font-size:18px;font-weight:700;border-bottom:2px solid #2A2A2A}
    .vs{margin-top:10px;font-size:12.5px;line-height:1.5}
    .bar{margin-top:12px;height:26px;background:repeating-linear-gradient(90deg,#2A2A2A 0 2px,transparent 2px 4px,#2A2A2A 4px 5px,transparent 5px 8px,#2A2A2A 8px 11px,transparent 11px 12px);opacity:.8}
    .thanks{text-align:center;font-size:11.5px;margin-top:6px;opacity:.75}
    .pass{display:flex}
    .pass .main{flex:1;min-width:0;padding:16px;color:var(--primary-text-color)}
    .pass .stub{flex:none;width:96px;background:#0E6E8C;color:#fff;padding:14px 10px;display:flex;flex-direction:column;justify-content:space-between;align-items:center;text-align:center;border-left:2px dashed rgba(255,255,255,.45)}
    .air{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--secondary-text-color)}
    .route{display:flex;align-items:center;gap:10px;margin:8px 0 12px}
    .route .p b{display:block;font-size:24px;font-weight:700;letter-spacing:.02em;line-height:1.05;text-transform:uppercase;max-width:9em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .route .p small{font-size:11.5px;color:var(--secondary-text-color)}
    .route .line{flex:1;min-width:20px;height:2px;background:repeating-linear-gradient(90deg,var(--secondary-text-color) 0 6px,transparent 6px 10px)}
    .fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
    .fields small{display:block;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--secondary-text-color)}
    .fields b{font-size:14.5px;font-weight:700;white-space:nowrap}
    .stub .big{font-size:28px;font-weight:700;line-height:1}
    .stub small{font-size:10px;letter-spacing:.12em;text-transform:uppercase;opacity:.85}
    .stub .sun{font-size:12px;font-weight:500}
    .strip .hd{display:flex;justify-content:space-between;align-items:baseline;color:var(--primary-text-color)}
    .strip .hd b{font-size:15px;font-weight:500}
    .strip svg{display:block;width:100%;height:auto;margin:6px 0}
    .tot{display:flex;justify-content:space-between;align-items:center;margin-top:10px;padding:10px 12px;border-radius:10px;background:rgba(var(--rgb-success-color,76,175,80),.14)}
    .tot b{font-size:22px;color:var(--success-color,#2e7d32)}
    .tot span{font-size:12.5px;color:var(--primary-text-color);text-align:right}
    .score{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:center;color:var(--primary-text-color)}
    .ring{position:relative;width:112px;height:112px}
    .ring svg{width:100%;height:100%;transform:rotate(-90deg)}
    .ring .c{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
    .ring .c b{font-size:24px;font-weight:700;line-height:1}
    .ring .c small{font-size:10px;color:var(--secondary-text-color);text-transform:uppercase;letter-spacing:.06em}
    .score ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
    .score li{display:flex;justify-content:space-between;gap:8px;font-size:13.5px;border-bottom:1px solid var(--divider-color);padding-bottom:5px}
    .badge{display:inline-flex;margin-top:10px;padding:5px 10px;border-radius:999px;background:rgba(var(--rgb-success-color,76,175,80),.14);color:var(--success-color,#2e7d32);font-size:12.5px;font-weight:500}
    @media (max-width:420px){.score{grid-template-columns:1fr}.ring{margin:0 auto}.pass .stub{width:80px}}
  `;

  class TripCard extends Base {
    static SUFFIX = "_last_trip";
    static KIND = "trips";
    static DEFAULT_STYLE = "pass";
    static EMPTY = "No trips yet. The first receipt appears after the next drive over a mile.";
    static STYLE = TRIP_STYLE;
    static getConfigElement() {
      return document.createElement("clockwatch-card-editor").withStyles("trip");
    }
    static getStubConfig() {
      return { style: "pass" };
    }
    _render() {
      super._render();
      const style = this._config && (this._config.style || TripCard.DEFAULT_STYLE);
      if (style === "score" && this._hass && !this._avgLoading && this._avg == null) {
        this._avgLoading = true;
        history(this._hass, this._config, "trips")
          .then((h) => {
            const t = ((h && h.trips) || []).filter((x) => x.miles_per_kwh);
            const kwh = t.reduce((a, x) => a + x.kwh, 0), mi = t.reduce((a, x) => a + x.miles, 0);
            this._avg = kwh > 0 ? mi / kwh : 0;
            this._rank = t;
          })
          .catch(() => (this._avg = 0))
          .finally(() => {
            this._avgLoading = false;
            super._render();
          });
      }
    }
    draw(style, r, f) {
      const from = r.from || "Start", to = r.to || "End";
      const route = r.from || r.to ? `${from} → ${to}` : f.day(r.started);
      const sun = r.sunshine != null ? `☀ ${Math.round(r.sunshine * 100)}%` : "";
      const car = r.compare_name || "a petrol car";
      if (style === "tillroll") {
        return `<div class="paper"><div class="phd"><h3>🧾 Trip receipt</h3>${sun ? `<span class="stamp">${esc(sun)} SUNSHINE</span>` : ""}</div>
          <div class="when">${esc(f.day(r.started))} · ${esc(f.time(r.started))} → ${esc(f.time(r.ended))}${r.from || r.to ? " · " + esc(route) : ""}</div>
          <div class="lines">
            <div class="ln"><span>Distance</span><b>${esc(f.dist(r.miles))}</b></div>
            <div class="ln"><span>Time</span><b>${esc(f.dur(r.minutes))}</b></div>
            <div class="ln"><span>Speed (avg / max)</span><b>${esc(f.speed(r.avg_mph))} / ${esc(f.speed(r.max_mph))} ${f.speedUnit}</b></div>
            <div class="ln"><span>Energy</span><b>${esc(f.kwh(r.kwh))}</b></div>
            <div class="ln"><span>Efficiency</span><b>${esc(f.eff(r.miles_per_kwh))}</b></div>
            ${r.outside_temp != null ? `<div class="ln"><span>Outside</span><b>${Math.round(r.outside_temp)} °C</b></div>` : ""}
          </div>
          <div class="total"><span>TOTAL</span><span>${esc(f.money(r.cost))}</span></div>
          <div class="vs">≈ ${esc(f.perDist(r.cost_per_mile))} · ${esc(car)} would have cost <b>${esc(f.money(r.petrol_cost))}</b> · you saved <b>${esc(f.money(r.saved))}</b></div>
          <div class="bar" aria-hidden="true"></div><div class="thanks">THANK YOU FOR DRIVING ELECTRIC</div></div>`;
      }
      if (style === "strip") {
        return `<div class="pad strip"><div class="hd"><b>${esc(route)}</b><small class="muted">${esc(f.time(r.started))} · ${esc(f.dur(r.minutes))}</small></div>
          <svg viewBox="0 0 320 90" role="img" aria-label="The drive, drawn as a line">
            <path d="M14 66 C60 66 70 36 110 40 S170 72 210 48 S270 18 306 26" fill="none" stroke="var(--divider-color)" stroke-width="10" stroke-linecap="round"/>
            <path d="M14 66 C60 66 70 36 110 40 S170 72 210 48 S270 18 306 26" fill="none" stroke="var(--primary-color)" stroke-width="4" stroke-linecap="round"/>
            <circle cx="14" cy="66" r="6" fill="var(--card-background-color,#fff)" stroke="var(--primary-color)" stroke-width="3"/><circle cx="306" cy="26" r="6" fill="var(--primary-color)"/>
            <text class="axis" x="14" y="86" style="font-size:10.5px;fill:var(--secondary-text-color)">${esc(from)}</text>
            <text x="306" y="48" text-anchor="end" style="font-size:10.5px;fill:var(--secondary-text-color)">${esc(to)}</text>
            <text x="160" y="12" text-anchor="middle" style="font-size:10.5px;fill:var(--secondary-text-color)">${r.max_mph ? esc(f.speed(r.max_mph)) + " " + f.speedUnit + " top · " : ""}${esc(f.eff(r.miles_per_kwh))}</text></svg>
          <div class="chips"><span class="chip"><b>${esc(f.dist(r.miles))}</b></span><span class="chip"><b>${esc(f.kwh(r.kwh))}</b></span>
          ${r.outside_temp != null ? `<span class="chip"><b>${Math.round(r.outside_temp)} °C</b></span>` : ""}${sun ? `<span class="chip">${esc(sun)} sunshine</span>` : ""}</div>
          <div class="tot"><b>${esc(f.money(r.cost))}</b><span>${esc(car)}: ${esc(f.money(r.petrol_cost))}<br>saved ${esc(f.money(r.saved))}</span></div></div>`;
      }
      if (style === "score") {
        const avg = this._avg;
        const vs = avg && r.miles_per_kwh ? Math.round((r.miles_per_kwh / avg - 1) * 100) : null;
        const ranked = (this._rank || []).filter((x) => String(x.ended).slice(0, 7) === String(r.ended).slice(0, 7)).map((x) => x.miles_per_kwh).sort((a, b) => b - a);
        const pos = r.miles_per_kwh ? ranked.indexOf(r.miles_per_kwh) + 1 : 0;
        const fill = Math.max(4, Math.min(100, ((r.miles_per_kwh || 0) / 5) * 100));
        const ord = (n) => n + (["th", "st", "nd", "rd"][((n % 100) - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th");
        const month = new Date(r.ended).toLocaleDateString(undefined, { month: "long" });
        return `<div class="pad"><div class="score"><div class="ring"><svg viewBox="0 0 42 42" aria-hidden="true"><circle cx="21" cy="21" r="16" fill="none" stroke="var(--divider-color)" stroke-width="5"/>
          <circle cx="21" cy="21" r="16" fill="none" stroke="var(--success-color,#2e7d32)" stroke-width="5" stroke-linecap="round" stroke-dasharray="${(fill * 100.5) / 100} 101"/></svg>
          <div class="c"><b>${r.miles_per_kwh ? (f.miles ? r.miles_per_kwh : r.miles_per_kwh * KM).toFixed(1) : "–"}</b><small>${f.miles ? "mi" : "km"} / kWh</small></div></div>
          <ul><li><span>${esc(route)}</span><b>${esc(f.dist(r.miles))}</b></li><li><span>Energy</span><b>${esc(f.kwh(r.kwh))}</b></li><li><span>Cost</span><b>${esc(f.money(r.cost))}</b></li>
          <li><span>vs your average</span><b style="color:${vs == null ? "inherit" : vs >= 0 ? "var(--success-color,#2e7d32)" : "var(--error-color,#db4437)"}">${vs == null ? "–" : (vs >= 0 ? "+" : "") + vs + "%"}</b></li></ul></div>
          ${pos && pos <= 3 && ranked.length >= 3 ? `<span class="badge">🏆 Your ${pos === 1 ? "" : ord(pos) + " "}most efficient trip in ${esc(month)}</span>` : ""}</div>`;
      }
      // boarding pass (default)
      return `<div class="pass"><div class="main"><div class="air">Clockwatch · ${esc(f.day(r.started))}</div>
        <div class="route"><div class="p"><b>${esc(from)}</b><small>${esc(f.time(r.started))}</small></div><div class="line"></div><div class="p" style="text-align:right"><b>${esc(to)}</b><small>${esc(f.time(r.ended))}</small></div></div>
        <div class="fields"><div><small>Distance</small><b>${esc(f.dist(r.miles))}</b></div><div><small>Energy</small><b>${esc(f.kwh(r.kwh))}</b></div><div><small>Efficiency</small><b>${esc(f.eff(r.miles_per_kwh))}</b></div>
        <div><small>Time</small><b>${esc(f.dur(r.minutes))}</b></div><div><small>Avg / max</small><b>${esc(f.speed(r.avg_mph))} / ${esc(f.speed(r.max_mph))}</b></div><div><small>Petrol fare</small><b>${esc(f.money(r.petrol_cost))}</b></div></div></div>
        <div class="stub"><small>Fare</small><span class="big">${esc(f.money(r.cost))}</span><span class="sun">${esc(sun)}</span><small>Saved ${esc(f.money(r.saved))}</small></div></div>`;
    }
  }

  // ------------------------------------------------------------------ month card
  const MONTH_STYLE = `
    .m h4{margin:0;font-size:16px;font-weight:500;display:flex;justify-content:space-between;align-items:baseline;color:var(--primary-text-color)}
    .kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0;color:var(--primary-text-color)}
    .kpis b{display:block;font-size:20px;font-weight:700}.kpis small{font-size:12px;color:var(--secondary-text-color)}
    .weeks{display:flex;align-items:flex-end;gap:10px;height:96px;padding:0 4px;border-bottom:1px solid var(--divider-color)}
    .wk{flex:1;display:flex;flex-direction:column-reverse;border-radius:6px 6px 2px 2px;overflow:hidden;min-width:0}
    .wk i{display:block}
    .wlab{display:flex;gap:10px;padding:6px 4px 0;font-size:11.5px;color:var(--secondary-text-color)}.wlab span{flex:1;text-align:center}
    .save{margin-top:12px;padding:10px 12px;border-radius:10px;background:rgba(var(--rgb-success-color,76,175,80),.14);color:var(--success-color,#2e7d32);font-weight:500}
    @media (max-width:420px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
  `;

  class MonthCard extends Base {
    static SUFFIX = "_charging_cost_this_month";
    static DEFAULT_STYLE = "month";
    static EMPTY = "Nothing this month yet.";
    static STYLE = MONTH_STYLE;
    static getConfigElement() {
      return document.createElement("clockwatch-card-editor").withStyles(null);
    }
    static getStubConfig() {
      return {};
    }
    _receipt() {
      const id = this._entityId();
      const st = id && this._hass && this._hass.states[id];
      return st && st.attributes && st.attributes.month ? st.attributes : null;
    }
    _navBar() {
      return "";
    }
    _render() {
      super._render();
      const m = this._receipt();
      if (m && this._weeksFor !== m.month && !this._loading) {
        this._loading = true;
        history(this._hass, this._config, "charges", m.month)
          .then((h) => {
            this._weeks = weeks((h && h.charges) || []);
            this._weeksFor = m.month;
          })
          .catch(() => (this._weeksFor = m.month))
          .finally(() => {
            this._loading = false;
            super._render();
          });
      }
    }
    draw(style, m, f) {
      const label = new Date(m.month + "-01T12:00:00").toLocaleDateString(undefined, { month: "long", year: "numeric" });
      const w = this._weeks || [];
      const max = Math.max(1, ...w.map((x) => x.solar + x.battery + x.grid));
      const bars = w.length
        ? `<div class="weeks" role="img" aria-label="Charging energy by week, by source">${w.map((x) => {
            const tot = x.solar + x.battery + x.grid;
            return `<div class="wk" style="height:${Math.max(4, (tot / max) * 100)}%">${tot ? `<i style="flex:${x.grid};background:${GRID}"></i><i style="flex:${x.battery};background:${BATT}"></i><i style="flex:${x.solar};background:${SUN}"></i>` : ""}</div>`;
          }).join("")}</div><div class="wlab">${w.map((x, i) => `<span>Wk ${i + 1}</span>`).join("")}</div>`
        : "";
      return `<div class="pad m"><h4>${esc(label)}<small class="muted">${m.charges} charges · ${m.trips} trips</small></h4>
        <div class="kpis"><div><b>${esc(f.dist(m.miles, 0))}</b><small>driven</small></div><div><b>${esc(f.money(m.charge_cost))}</b><small>charging</small></div>
        <div><b>${esc(f.perDist(m.cost_per_mile))}</b><small>per ${f.miles ? "mile" : "km"}</small></div><div><b>${esc(f.pct(m.solar_share))}</b><small>from the sun</small></div></div>
        ${bars}${m.petrol_cost > 0 ? `<div class="save">⛽ vs petrol this month: ${esc(f.money(m.saved))} saved</div>` : ""}</div>`;
    }
  }

  function weeks(charges) {
    const out = [0, 1, 2, 3, 4].map(() => ({ solar: 0, battery: 0, grid: 0 }));
    for (const c of charges) {
      const d = new Date(c.ended).getDate();
      const w = out[Math.min(4, Math.floor((d - 1) / 7))];
      w.solar += c.energy.solar;
      w.battery += c.energy.battery;
      w.grid += c.energy.grid;
    }
    while (out.length > 4 && out[out.length - 1].solar + out[out.length - 1].battery + out[out.length - 1].grid === 0) out.pop();
    return out;
  }

  // ------------------------------------------------------------------ editor (shared)
  const STYLES = {
    charge: [["curve", "Charging curve"], ["classic", "Classic"], ["pump", "Pump display"], ["minimal", "Minimal"]],
    trip: [["pass", "Boarding pass"], ["tillroll", "Till roll"], ["strip", "Route strip"], ["score", "Scorecard"]],
  };
  class Editor extends HTMLElement {
    withStyles(kind) {
      this._kind = kind;
      return this;
    }
    setConfig(config) {
      this._config = { ...config };
      this._draw();
    }
    set hass(hass) {
      this._hass = hass;
      if (this._form) this._form.hass = hass;
    }
    _draw() {
      if (!this._form) {
        this._form = document.createElement("ha-form");
        const schema = [];
        if (this._kind) schema.push({ name: "style", selector: { select: { mode: "dropdown", options: STYLES[this._kind].map(([value, label]) => ({ value, label })) } } });
        schema.push(
          { name: "units", selector: { select: { mode: "dropdown", options: [{ value: "auto", label: "Same as Home Assistant" }, { value: "mi", label: "Miles" }, { value: "km", label: "Kilometres" }] } } },
          { name: "entity", selector: { entity: { domain: "sensor", integration: DOMAIN } } },
        );
        this._form.schema = schema;
        this._form.computeLabel = (s) => ({ style: "Style", units: "Distances in", entity: "Sensor (only needed with more than one car)" })[s.name];
        this._form.addEventListener("value-changed", (e) => {
          const config = { ...this._config, ...e.detail.value };
          Object.keys(config).forEach((k) => (config[k] === "" || config[k] == null || (k === "units" && config[k] === "auto")) && delete config[k]);
          this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
        });
        this.appendChild(this._form);
      }
      this._form.data = { units: "auto", ...(this._kind ? { style: STYLES[this._kind][0][0] } : {}), ...this._config };
      if (this._hass) this._form.hass = this._hass;
    }
  }

  const define = (tag, cls) => customElements.get(tag) || customElements.define(tag, cls);
  define("clockwatch-card-editor", Editor);
  define("clockwatch-charge-card", ChargeCard);
  define("clockwatch-trip-card", TripCard);
  define("clockwatch-month-card", MonthCard);
  window.customCards = window.customCards || [];
  for (const [type, name, description] of [
    ["clockwatch-charge-card", "Clockwatch charge", "The last charge's receipt: where the energy came from, what it cost, cost per mile."],
    ["clockwatch-trip-card", "Clockwatch trip", "The last drive's receipt: distance, efficiency, cost, sunshine and the petrol comparison."],
    ["clockwatch-month-card", "Clockwatch month", "This month's charging cost, miles, cost per mile, solar share and petrol saving."],
  ]) {
    if (!window.customCards.some((c) => c.type === type)) window.customCards.push({ type, name, description, preview: false, documentationURL: "https://github.com/SinghTejveer/clockwatch" });
  }
  console.info(`%c CLOCKWATCH-CARDS %c ${VERSION} `, "color:#fff;background:#1AA6A0;font-weight:700", "color:#1AA6A0");
})();
