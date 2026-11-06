(async function () {
  'use strict';
  const { $, $$, html, icon, fmt, api, field } = App;
  await App.boot({ role: 'ADMIN', nav: 'attendance' });
  $('#searchIcon').innerHTML = icon('search');
  $('#settingsBtn').innerHTML = html`${icon('sliders')} Office location`;
  $('#excelBtn').innerHTML = html`${icon('spreadsheet')} Export Excel`;

  const today = new Date();
  const state = { page: 1, pageSize: 15, search: '', department: '', from: fmt.iso(new Date(today.getFullYear(), today.getMonth(), 1)), to: App.todayISO(), late: '', tab: 'records' };
  $('#from').value = state.from;
  $('#to').value = state.to;

  try {
    const meta = await api.get('/employees/meta/');
    $('#department').innerHTML = html`<option value="">All departments</option>${meta.departments.map(name => html`<option value="${name}">${name}</option>`)}`;
  } catch (error) { /* department filter stays at "All" */ }

  const filters = () => ({ search: state.search, department: state.department, from: state.from, to: state.to, late: state.late });
  const lateCell = minutes => (minutes == null ? html`<span class="muted" title="No shift assigned">—</span>` : minutes > 0 ? html`<span class="badge badge-warning">${minutes} min</span>` : html`<span class="badge badge-success">On time</span>`);

  async function loadSummary() {
    try {
      const data = await api.get('/attendance/', { ...filters(), summary: 'true' });
      const t = data.totals;
      $('#stats').innerHTML = html`
        <div class="card stat"><span class="stat-icon">${icon('users')}</span><div><div class="stat-label">Employees</div><div class="stat-value">${t.employees}</div><div class="stat-note">${t.records} check-ins</div></div></div>
        <div class="card stat"><span class="stat-icon amber">${icon('clock')}</span><div><div class="stat-label">Late check-ins</div><div class="stat-value">${t.late_days}</div><div class="stat-note">${t.records ? Math.round(100 * t.late_days / t.records) : 0}% of check-ins</div></div></div>
        <div class="card stat"><span class="stat-icon amber">${icon('timer')}</span><div><div class="stat-label">Late minutes</div><div class="stat-value">${fmt.number(t.late_minutes)}</div><div class="stat-note">${t.late_days ? Math.round(t.late_minutes / t.late_days) : 0} min average when late</div></div></div>
        <div class="card stat"><span class="stat-icon blue">${icon('briefcase')}</span><div><div class="stat-label">Hours worked</div><div class="stat-value">${fmt.number(Math.round(t.worked_minutes / 60))}</div><div class="stat-note">${fmt.date(state.from)} – ${fmt.date(state.to)}</div></div></div>`;
      if (state.tab === 'summary') {
        $('#summaryRows').innerHTML = data.employees.length ? html`${data.employees.map(r => html`<tr>
          <td><div class="cell-main">${r.employee_name}</div><div class="cell-sub mono">${r.employee_code}</div></td><td>${r.department || '—'}</td>
          <td class="right num">${r.days_present}</td><td class="right num">${r.late_days}</td><td class="right num">${fmt.number(r.late_minutes)}</td>
          <td class="right num">${r.average_late_minutes ? `${r.average_late_minutes} min` : '—'}</td><td class="right num">${fmt.duration(r.worked_minutes)}</td></tr>`)}`
          : App.emptyRow(7, { iconName: 'pin', title: 'No attendance in this period', text: 'Try a wider date range or clear the filters.' });
      }
    } catch (error) {
      $('#stats').innerHTML = '';
      if (state.tab === 'summary') { $('#summaryRows').innerHTML = App.errorRow(7, error.message); $('[data-retry]', $('#summaryRows')).addEventListener('click', load); }
    }
  }

  async function loadRecords() {
    const rows = $('#rows');
    rows.innerHTML = App.skeletonRows(9, 6);
    try {
      const data = await api.get('/attendance/', { ...filters(), page: state.page, page_size: state.pageSize });
      if (!data.results.length && state.page > 1) { state.page -= 1; return loadRecords(); }
      const dist = v => (v == null ? '—' : `${v} m`);
      rows.innerHTML = data.results.length ? html`${data.results.map(r => html`<tr>
        <td><div class="cell-main">${r.employee_name}</div><div class="cell-sub mono">${r.employee_code || r.employee_username}</div></td>
        <td class="nowrap">${fmt.date(r.date)}${r.is_corrected ? html`<div>${App.badge('CORRECTED')}</div>` : ''}</td><td>${r.shift_name || html`<span class="muted">No shift</span>`}${r.scheduled_start ? html`<div class="cell-sub">starts ${fmt.time(r.scheduled_start)}</div>` : ''}</td>
        <td>${fmt.time(r.check_in_at)}</td><td class="right">${lateCell(r.late_minutes)}</td><td>${r.check_out_at ? fmt.time(r.check_out_at) : '—'}</td>
        <td class="right num">${r.worked_minutes == null ? '—' : fmt.duration(r.worked_minutes)}</td>
        <td class="right num">${dist(r.check_in_distance_meters)} / ${dist(r.check_out_distance_meters)}</td><td>${App.badge(r.status)}</td></tr>`)}`
        : App.emptyRow(9, { iconName: 'pin', title: 'No attendance records', text: state.search || state.department || state.late ? 'Try a different search or filter.' : 'Records appear when employees check in.' });
      App.pager($('#pager'), { page: state.page, count: data.count, pageSize: state.pageSize }, page => { state.page = page; loadRecords(); });
    } catch (error) {
      rows.innerHTML = App.errorRow(9, error.message);
      $('[data-retry]', rows).addEventListener('click', load);
      $('#pager').hidden = true;
    }
  }

  function load() {
    loadSummary();
    if (state.tab === 'records') loadRecords(); else $('#pager').hidden = true;
  }

  function setTab(tab) {
    state.tab = tab;
    $('#tabRecords').setAttribute('aria-selected', String(tab === 'records'));
    $('#tabSummary').setAttribute('aria-selected', String(tab === 'summary'));
    $('#recordsPane').hidden = tab !== 'records';
    $('#summaryPane').hidden = tab !== 'summary';
    load();
  }

  function ensureLeaflet() {
    return new Promise((resolve, reject) => {
      if (window.L) return resolve(window.L);
      if (!document.querySelector('link[href*="leaflet.css"]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'vendor/leaflet/leaflet.css';
        document.head.appendChild(link);
      }
      const script = document.createElement('script');
      script.src = 'vendor/leaflet/leaflet.js';
      script.onload = () => resolve(window.L);
      script.onerror = () => {
        const cdn = document.createElement('script');
        cdn.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        cdn.onload = () => resolve(window.L);
        cdn.onerror = () => reject(new Error('Could not load map library.'));
        document.head.appendChild(cdn);
      };
      document.head.appendChild(script);
    });
  }

  async function openSettings() {
    let s;
    try { s = await api.get('/attendance/settings/'); } catch (error) { return App.error(error); }

    let L;
    try {
      L = await ensureLeaflet();
    } catch (err) {
      return App.toast('Could not initialize map component: ' + err.message, 'error');
    }

    if (L && L.Icon && L.Icon.Default) {
      delete L.Icon.Default.prototype._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'vendor/leaflet/marker-icon-2x.png',
        iconUrl: 'vendor/leaflet/marker-icon.png',
        shadowUrl: 'vendor/leaflet/marker-shadow.png',
      });
    }

    const initialLat = s.latitude ? Number(s.latitude) : 17.385044;
    const initialLng = s.longitude ? Number(s.longitude) : 78.486671;
    const hasInitialCoords = s.latitude != null && s.longitude != null;
    let initialRadius = Number(s.radius_meters) || 100;
    let initialLocationName = s.location_name || '';

    let mapInstance = null;
    let markerInstance = null;
    let circleInstance = null;
    let activeReverseGeocodeTimer = null;

    App.modal({
      title: 'Office Attendance Location',
      subtitle: 'Select the official office location and permitted check-in radius on the map.',
      submitLabel: 'Save location',
      cancelLabel: 'Cancel',
      wide: true,
      body: html`
        <div class="map-picker-container">
          <div class="map-toolbar">
            <div class="map-search-wrap">
              <span class="map-search-icon">${icon('search')}</span>
              <input type="search" class="input" id="mapSearchInput" placeholder="Search address, landmark, office, city..." autocomplete="off">
              <button type="button" class="map-search-clear" id="mapSearchClear" title="Clear search">&times;</button>
              <ul class="map-search-dropdown" id="mapSearchDropdown"></ul>
            </div>
            <button class="btn btn-sm" type="button" id="useCurrentLocationBtn">
              ${icon('pin', 'icon-sm')} Use my current location
            </button>
            <button class="btn btn-sm" type="button" id="fitRadiusBtn" title="Fit map view to radius">
              ${icon('layers', 'icon-sm')} Focus radius
            </button>
          </div>

          <div id="attendanceMap" class="attendance-map" aria-label="Interactive map for selecting office location"></div>

          <div class="map-info-card">
            <div class="map-location-title">
              ${icon('pin')}
              <span id="selectedLocationDisplay">${initialLocationName || (hasInitialCoords ? 'Configured office location' : 'Click anywhere on map or search to place pin')}</span>
            </div>
            <div class="map-coords-badge" id="selectedCoordsDisplay">
              ${hasInitialCoords ? `${initialLat.toFixed(6)}, ${initialLng.toFixed(6)}` : 'No coordinates selected'}
            </div>
          </div>

          <div class="form-grid" style="margin-top:4px">
            <div class="field span-2">
              <label class="label" for="radiusInput">Permitted attendance radius: <strong id="radiusValueDisplay">${initialRadius} m</strong></label>
              <div class="radius-slider-group">
                <input type="range" class="input" id="radiusSlider" min="10" max="1500" step="5" value="${initialRadius}">
                <input type="number" class="input" id="radiusInput" name="radius_meters" min="10" max="10000" step="5" value="${initialRadius}" style="width:110px">
              </div>
              <div class="radius-pills">
                <span class="muted" style="font-size:12px;margin-right:4px;align-self:center">Presets:</span>
                <button type="button" class="radius-pill" data-radius="50">50 m</button>
                <button type="button" class="radius-pill" data-radius="100">100 m</button>
                <button type="button" class="radius-pill" data-radius="250">250 m</button>
                <button type="button" class="radius-pill" data-radius="500">500 m</button>
                <button type="button" class="radius-pill" data-radius="1000">1,000 m</button>
              </div>
              <span class="hint">Employees can only check in and out when their GPS coordinates fall inside this circle.</span>
            </div>

            ${field({ label: 'Latitude', name: 'latitude', type: 'number', value: s.latitude ?? '', required: true, attrs: 'id="latInput" step="any" min="-90" max="90"' })}
            ${field({ label: 'Longitude', name: 'longitude', type: 'number', value: s.longitude ?? '', required: true, attrs: 'id="lngInput" step="any" min="-180" max="180"' })}
            ${field({ label: 'Location name / label', name: 'location_name', type: 'text', value: initialLocationName, placeholder: 'e.g. Headquarters, Tech Park Campus', span2: true, attrs: 'id="locationNameInput"' })}
            ${field({ label: 'Enable location-based attendance for this company', name: 'is_enabled', type: 'checkbox', value: s.is_enabled, span2: true })}
          </div>

          <div class="map-helper-tip">
            ${icon('info', 'icon-sm')}
            <span>Tip: Drag the pin or click anywhere on the map to adjust the exact location.</span>
          </div>
        </div>
      `,
      onOpen: ({ dialog, form }) => {
        dialog.classList.add('map-modal');

        const mapEl = form.querySelector('#attendanceMap');
        const latInput = form.querySelector('#latInput');
        const lngInput = form.querySelector('#lngInput');
        const locNameInput = form.querySelector('#locationNameInput');
        const radiusInput = form.querySelector('#radiusInput');
        const radiusSlider = form.querySelector('#radiusSlider');
        const radiusDisplay = form.querySelector('#radiusValueDisplay');
        const locDisplay = form.querySelector('#selectedLocationDisplay');
        const coordsDisplay = form.querySelector('#selectedCoordsDisplay');
        const searchInput = form.querySelector('#mapSearchInput');
        const searchClear = form.querySelector('#mapSearchClear');
        const searchDropdown = form.querySelector('#mapSearchDropdown');
        const useCurrentBtn = form.querySelector('#useCurrentLocationBtn');
        const fitBtn = form.querySelector('#fitRadiusBtn');
        const presetPills = form.querySelectorAll('.radius-pill');

        let currentLat = initialLat;
        let currentLng = initialLng;
        let currentRadius = initialRadius;
        let currentLocationName = initialLocationName;

        mapInstance = L.map(mapEl, {
          center: [currentLat, currentLng],
          zoom: hasInitialCoords ? 16 : 14,
          zoomControl: true,
        });

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19,
          attribution: '&copy; OpenStreetMap contributors',
        }).addTo(mapInstance);

        markerInstance = L.marker([currentLat, currentLng], {
          draggable: true,
          autoPan: true,
        }).addTo(mapInstance);

        circleInstance = L.circle([currentLat, currentLng], {
          radius: currentRadius,
          color: '#047857',
          fillColor: '#047857',
          fillOpacity: 0.16,
          weight: 2,
        }).addTo(mapInstance);

        markerInstance.bindPopup('<strong>Office Attendance Location</strong><br><span id="markerPopupText">' + (currentLocationName || 'Selected attendance point') + '</span>');
        if (hasInitialCoords) {
          markerInstance.openPopup();
        }

        setTimeout(() => {
          if (mapInstance) {
            mapInstance.invalidateSize();
            if (hasInitialCoords) {
              mapInstance.setView([currentLat, currentLng], 16);
            }
          }
        }, 150);

        function updateUI(lat, lng, radius, name, shouldReverse = false, zoomLevel = null) {
          currentLat = Number(lat);
          currentLng = Number(lng);
          currentRadius = Number(radius);

          latInput.value = currentLat.toFixed(6);
          lngInput.value = currentLng.toFixed(6);
          coordsDisplay.textContent = `${currentLat.toFixed(6)}, ${currentLng.toFixed(6)}`;

          if (name) {
            currentLocationName = name;
            locNameInput.value = name;
            locDisplay.textContent = name;
            const popupEl = document.getElementById('markerPopupText');
            if (popupEl) popupEl.textContent = name;
          }

          markerInstance.setLatLng([currentLat, currentLng]);
          circleInstance.setLatLng([currentLat, currentLng]);
          circleInstance.setRadius(currentRadius);

          if (zoomLevel) {
            mapInstance.setView([currentLat, currentLng], zoomLevel);
          }

          presetPills.forEach(p => {
            p.classList.toggle('active', Number(p.dataset.radius) === currentRadius);
          });

          if (shouldReverse) {
            clearTimeout(activeReverseGeocodeTimer);
            activeReverseGeocodeTimer = setTimeout(async () => {
              locDisplay.textContent = 'Identifying place…';
              try {
                const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${currentLat}&lon=${currentLng}&zoom=18&addressdetails=1`, {
                  headers: { 'Accept': 'application/json' }
                });
                if (res.ok) {
                  const data = await res.json();
                  if (data && data.display_name) {
                    const cleanName = data.display_name;
                    locDisplay.textContent = cleanName;
                    if (!locNameInput.value || locNameInput.value === initialLocationName) {
                      locNameInput.value = cleanName.split(',').slice(0, 3).join(',').trim();
                    }
                    const popupEl = document.getElementById('markerPopupText');
                    if (popupEl) popupEl.textContent = locNameInput.value || cleanName;
                  }
                }
              } catch (_) {
                locDisplay.textContent = `${currentLat.toFixed(6)}, ${currentLng.toFixed(6)}`;
              }
            }, 600);
          }
        }

        mapInstance.on('click', e => {
          updateUI(e.latlng.lat, e.latlng.lng, currentRadius, null, true);
        });

        markerInstance.on('drag', e => {
          const pos = e.target.getLatLng();
          circleInstance.setLatLng(pos);
          coordsDisplay.textContent = `${pos.lat.toFixed(6)}, ${pos.lng.toFixed(6)}`;
          latInput.value = pos.lat.toFixed(6);
          lngInput.value = pos.lng.toFixed(6);
        });

        markerInstance.on('dragend', e => {
          const pos = e.target.getLatLng();
          updateUI(pos.lat, pos.lng, currentRadius, null, true);
        });

        const onRadiusChange = val => {
          const r = Math.max(10, Math.min(10000, Number(val) || 100));
          currentRadius = r;
          radiusInput.value = r;
          radiusSlider.value = Math.min(1500, r);
          radiusDisplay.textContent = `${r} m`;
          circleInstance.setRadius(r);
          presetPills.forEach(p => p.classList.toggle('active', Number(p.dataset.radius) === r));
        };

        radiusSlider.addEventListener('input', e => onRadiusChange(e.target.value));
        radiusInput.addEventListener('input', e => onRadiusChange(e.target.value));

        presetPills.forEach(pill => {
          pill.addEventListener('click', () => onRadiusChange(pill.dataset.radius));
        });

        const onManualCoordChange = () => {
          const lat = parseFloat(latInput.value);
          const lng = parseFloat(lngInput.value);
          if (!isNaN(lat) && !isNaN(lng) && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) {
            updateUI(lat, lng, currentRadius, null, true, 16);
          }
        };
        latInput.addEventListener('change', onManualCoordChange);
        lngInput.addEventListener('change', onManualCoordChange);

        fitBtn.addEventListener('click', () => {
          if (circleInstance && mapInstance) {
            mapInstance.fitBounds(circleInstance.getBounds(), { padding: [40, 40] });
          }
        });

        useCurrentBtn.addEventListener('click', () => {
          if (!navigator.geolocation) return App.toast('Your browser does not support geolocation.', 'error');
          useCurrentBtn.disabled = true;
          const origHtml = useCurrentBtn.innerHTML;
          useCurrentBtn.innerHTML = '<span class="spinner"></span> Detecting GPS…';
          navigator.geolocation.getCurrentPosition(
            p => {
              useCurrentBtn.disabled = false;
              useCurrentBtn.innerHTML = origHtml;
              updateUI(p.coords.latitude, p.coords.longitude, currentRadius, null, true, 17);
              App.toast('Location updated from device GPS.');
            },
            err => {
              useCurrentBtn.disabled = false;
              useCurrentBtn.innerHTML = origHtml;
              App.toast('Could not detect GPS location (' + (err.message || 'permission denied') + ').', 'error');
            },
            { enableHighAccuracy: true, timeout: 12000 }
          );
        });

        let searchDebounceTimer = null;
        searchInput.addEventListener('input', () => {
          const query = searchInput.value.trim();
          searchClear.style.display = query ? 'block' : 'none';
          clearTimeout(searchDebounceTimer);
          if (query.length < 2) {
            searchDropdown.style.display = 'none';
            searchDropdown.innerHTML = '';
            return;
          }
          searchDropdown.style.display = 'block';
          searchDropdown.innerHTML = '<li style="color:var(--text-muted);cursor:default">Searching places…</li>';
          searchDebounceTimer = setTimeout(async () => {
            try {
              const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=6&addressdetails=1`, {
                headers: { 'Accept': 'application/json' }
              });
              if (!res.ok) throw new Error('Search failed');
              const results = await res.json();
              if (!results || !results.length) {
                searchDropdown.innerHTML = '<li style="color:var(--text-muted);cursor:default">No locations found. Try a different query.</li>';
                return;
              }
              searchDropdown.innerHTML = results.map((r, i) => {
                const parts = (r.display_name || '').split(',');
                const mainName = parts[0] || r.name || 'Location';
                const subName = parts.slice(1, 4).join(',').trim();
                return `<li data-index="${i}">
                  <span class="res-name">${App.esc(mainName)}</span>
                  <span class="res-sub">${App.esc(subName)}</span>
                </li>`;
              }).join('');

              $$('li[data-index]', searchDropdown).forEach(el => {
                el.addEventListener('click', () => {
                  const item = results[Number(el.dataset.index)];
                  if (item) {
                    const lat = parseFloat(item.lat);
                    const lon = parseFloat(item.lon);
                    const placeTitle = (item.display_name || '').split(',').slice(0, 3).join(',').trim();
                    searchInput.value = placeTitle;
                    searchDropdown.style.display = 'none';
                    updateUI(lat, lon, currentRadius, placeTitle, false, 17);
                    App.toast('Moved to ' + placeTitle);
                  }
                });
              });
            } catch (err) {
              searchDropdown.innerHTML = '<li style="color:var(--text-muted);cursor:default">Search error. You can click directly on the map.</li>';
            }
          }, 350);
        });

        searchClear.addEventListener('click', () => {
          searchInput.value = '';
          searchClear.style.display = 'none';
          searchDropdown.style.display = 'none';
          searchDropdown.innerHTML = '';
        });

        dialog.addEventListener('click', e => {
          if (!searchDropdown.contains(e.target) && e.target !== searchInput) {
            searchDropdown.style.display = 'none';
          }
        });
      },
      onSubmit: async (formData, ctx) => {
        const lat = formData.get('latitude');
        const lng = formData.get('longitude');
        const radius = formData.get('radius_meters');
        const locationName = (formData.get('location_name') || '').trim();
        const isEnabled = formData.get('is_enabled') === 'on';

        if (!lat || !lng) {
          throw new Error('Please select an office location on the map.');
        }

        await api.put('/attendance/settings/', {
          latitude: lat,
          longitude: lng,
          radius_meters: radius,
          location_name: locationName,
          is_enabled: isEnabled,
        });

        if (mapInstance) {
          mapInstance.remove();
          mapInstance = null;
        }
        ctx.close();
        App.toast('Office attendance location and radius saved successfully.');
      },
    });
  }

  const refilter = () => { state.page = 1; load(); };
  $('#tabRecords').addEventListener('click', () => setTab('records'));
  $('#tabSummary').addEventListener('click', () => setTab('summary'));
  $('#settingsBtn').addEventListener('click', openSettings);
  $('#excelBtn').addEventListener('click', () => App.download('/reports/excel/attendance/', `attendance_${state.from}_${state.to}.xlsx`, { department: state.department, from: state.from, to: state.to, late: state.late === 'true' ? 'true' : '' }));
  $('#search').addEventListener('input', App.debounce(e => { state.search = e.target.value.trim(); refilter(); }));
  $('#department').addEventListener('change', e => { state.department = e.target.value; refilter(); });
  $('#late').addEventListener('change', e => { state.late = e.target.value; refilter(); });
  $('#from').addEventListener('change', e => { state.from = e.target.value; refilter(); });
  $('#to').addEventListener('change', e => { state.to = e.target.value; refilter(); });
  load();
})();
