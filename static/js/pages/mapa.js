const OVERLAY_DEFAULT_OPACITY = 0.85;

const state = {
    map: null,
    txMarker: null,
    txData: null,
    txCoords: null,
    rxEntries: [],
    selectedRxIndex: null,
    linkLine: null,
    coverageOverlay: null,
    CoverageOverlayClass: null,
    radiusCircle: null,
    coverageData: null,
    coverageRadiusKm: null,
    coverageStale: false,
    coverageUnit: 'dbuv',
    coverageImages: null,
    coverageScales: null,
    signalLevelDict: { dbuv: {}, dbm: {} },
    lossComponents: null,
    centerMetrics: null,
    overlayOpacity: OVERLAY_DEFAULT_OPACITY,
    elevationService: null,
    pendingTiltTimeout: null,
};

function ensureCoverageOverlayClass() {
    if (state.CoverageOverlayClass) {
        return state.CoverageOverlayClass;
    }
    class CoverageImageOverlay extends google.maps.OverlayView {
        constructor(bounds, imageSrc, opacity) {
            super();
            this.bounds = bounds;
            this.imageSrc = imageSrc;
            this.opacity = opacity;
            this.div = null;
            this.img = null;
        }

        onAdd() {
            this.div = document.createElement('div');
            this.div.style.position = 'absolute';
            this.div.style.pointerEvents = 'none';

            this.img = document.createElement('img');
            this.img.src = this.imageSrc;
            this.img.style.position = 'absolute';
            this.img.style.width = '100%';
            this.img.style.height = '100%';
            this.img.style.opacity = this.opacity;
            this.img.style.pointerEvents = 'none';

            this.div.appendChild(this.img);
            const panes = this.getPanes();
            panes.overlayLayer.appendChild(this.div);
        }

        draw() {
            if (!this.div) return;
            const projection = this.getProjection();
            const sw = projection.fromLatLngToDivPixel(this.bounds.getSouthWest());
            const ne = projection.fromLatLngToDivPixel(this.bounds.getNorthEast());

            this.div.style.left = `${sw.x}px`;
            this.div.style.top = `${ne.y}px`;
            this.div.style.width = `${ne.x - sw.x}px`;
            this.div.style.height = `${sw.y - ne.y}px`;
        }

        onRemove() {
            if (this.div && this.div.parentNode) {
                this.div.parentNode.removeChild(this.div);
            }
            this.div = null;
            this.img = null;
        }

        setOpacity(opacity) {
            this.opacity = opacity;
            if (this.img) {
                this.img.style.opacity = opacity;
            }
        }
    }

    state.CoverageOverlayClass = CoverageImageOverlay;
    return CoverageImageOverlay;
}

function formatNumber(value, suffix = '') {
    if (value === undefined || value === null || Number.isNaN(value)) {
        return '-';
    }
    return `${Number(value).toFixed(2)}${suffix}`;
}

function formatDbValue(value, unit = 'dB') {
    if (value === undefined || value === null || Number.isNaN(value)) {
        return '-';
    }
    return `${Number(value).toFixed(1)} ${unit}`;
}

let locationUpdateAbort = null;

function syncTxLocation(latLng) {
    if (!latLng) return;
    const payload = {
        latitude: latLng.lat(),
        longitude: latLng.lng(),
    };

    if (locationUpdateAbort) {
        locationUpdateAbort.abort();
    }
    locationUpdateAbort = new AbortController();

    fetch('/tx-location', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: locationUpdateAbort.signal,
    }).then((response) => {
        if (!response.ok) {
            throw new Error('Falha ao atualizar localização da TX');
        }
        return response.json();
    }).then((data) => {
        if (!state.txData) {
            state.txData = {};
        }
        if (data.municipality !== undefined) {
            state.txData.txLocationName = data.municipality;
        }
        if (data.elevation !== undefined) {
            state.txData.txElevation = data.elevation;
        }
        updateTxSummary(state.txData);
    }).catch((error) => {
        if (error.name === 'AbortError') {
            return;
        }
        console.error(error);
    }).finally(() => {
        locationUpdateAbort = null;
    });
}

function formatDb(value) {
    if (value === undefined || value === null || Number.isNaN(value)) {
        return '-';
    }
    return `${Number(value).toFixed(2)} dB`;
}

function updateRadiusLabel() {
    const radiusInput = document.getElementById('radiusInput');
    const radiusValue = document.getElementById('radiusValue');
    radiusValue.textContent = `${radiusInput.value} km`;
}

function updateTiltLabel(value) {
    document.getElementById('tiltValue').textContent = `${Number(value).toFixed(1)}°`;
}

function updateTxSummary(data) {
    document.getElementById('txLat').textContent = formatNumber(data.latitude, '°');
    document.getElementById('txLng').textContent = formatNumber(data.longitude, '°');
    document.getElementById('txFreq').textContent = data.frequency ? `${Number(data.frequency).toFixed(2)} MHz` : '-';
    document.getElementById('txModel').textContent = data.propagationModel || '-';
    updateTiltLabel(data.antennaTilt || 0);
    document.getElementById('tiltControl').value = data.antennaTilt ?? 0;

    const municipalityEl = document.getElementById('txMunicipio');
    if (municipalityEl) {
        municipalityEl.textContent = data.txLocationName || '-';
    }
    const elevationEl = document.getElementById('txElevation');
    if (elevationEl) {
        const elevation = data.txElevation !== undefined && data.txElevation !== null
            ? `${Number(data.txElevation).toFixed(1)} m`
            : '-';
        elevationEl.textContent = elevation;
    }
    const climateEl = document.getElementById('txClimateInfo');
    if (climateEl) {
        if (data.climateUpdatedAt) {
            const date = new Date(data.climateUpdatedAt);
            climateEl.textContent = `Clima ajustado em ${date.toLocaleString('pt-BR', { timeZone: 'UTC' })} UTC`;
        } else {
            climateEl.textContent = 'Clima não ajustado para esta localização';
        }
    }
}

function updateGainSummary(gainComponents) {
    if (!gainComponents) {
        document.getElementById('gainBase').textContent = '-';
        document.getElementById('gainHorizontal').textContent = '-';
        document.getElementById('gainVertical').textContent = '-';
        return;
    }
    document.getElementById('gainBase').textContent = formatDb(gainComponents.base_gain_dbi || 0);
    if (gainComponents.horizontal_adjustment_db_min !== undefined) {
        const min = formatDb(gainComponents.horizontal_adjustment_db_min);
        const max = formatDb(gainComponents.horizontal_adjustment_db_max);
        document.getElementById('gainHorizontal').textContent = `${min} / ${max}`;
    } else {
        document.getElementById('gainHorizontal').textContent = '-';
    }
    if (gainComponents.vertical_adjustment_db_min !== undefined) {
        const minV = formatDb(gainComponents.vertical_adjustment_db_min);
        const maxV = formatDb(gainComponents.vertical_adjustment_db_max);
        document.getElementById('gainVertical').textContent = `${minV} / ${maxV}`;
    } else {
        document.getElementById('gainVertical').textContent = '-';
    }
}

function updateScaleReadout(unitKey = state.coverageUnit || 'dbuv') {
    if (!state.coverageData || !state.coverageData.scale) {
        document.getElementById('fieldScale').textContent = '-';
        return;
    }
    const scaleInfo = state.coverageData.scale.units || {};
    const entry = scaleInfo[unitKey] || { min: state.coverageData.scale.min, max: state.coverageData.scale.max };
    const label = unitKey === 'dbm' ? 'dBm' : 'dBµV/m';
    if (entry && entry.min !== undefined && entry.max !== undefined) {
        document.getElementById('fieldScale').textContent = `${formatNumber(entry.min)} – ${formatNumber(entry.max)} ${label}`;
    } else {
        document.getElementById('fieldScale').textContent = '-';
    }
}

function showToast(message, isError = false) {
    const card = document.getElementById('mapTooltip');
    if (!card) return;
    card.innerHTML = `<h4>${isError ? 'Atenção' : 'Cobertura'}</h4><p>${message}</p>`;
    card.hidden = false;
    setTimeout(() => {
        card.hidden = true;
    }, 3600);
}

function setCoverageStatus(message) {
    const badge = document.getElementById('coverageStatus');
    if (!badge) return;
    if (message) {
        badge.hidden = false;
        badge.innerHTML = message;
    } else {
        badge.hidden = true;
        badge.textContent = '';
    }
}

function setCoverageLoading(isLoading) {
    const spinner = document.getElementById('coverageSpinner');
    const button = document.getElementById('btnGenerateCoverage');
    if (spinner) {
        spinner.hidden = !isLoading;
    }
    if (button) {
        button.disabled = isLoading;
    }
}

function markCoverageStale(message = 'Cobertura desatualizada. Gere novamente.') {
    state.coverageStale = true;
    setCoverageStatus(message);
    state.signalLevelDict = { dbuv: {}, dbm: {} };
    state.rxEntries.forEach((entry, idx) => {
        if (!entry.summary) return;
        const inside = entry.summary.insideCoverage !== false;
        entry.summary.field_dbuv = undefined;
        entry.summary.field_dbm = undefined;
        entry.summary.pendingField = inside;
        if (idx === state.selectedRxIndex) {
            updateLinkSummary(entry.summary);
        }
    });
    renderRxList();
}

function clearCoverageStatus() {
    state.coverageStale = false;
    setCoverageStatus('');
}

function updateUnitButtons(unitKey) {
    const buttons = {
        dbuv: document.getElementById('unitDbuv'),
        dbm: document.getElementById('unitDbm'),
    };
    Object.entries(buttons).forEach(([key, button]) => {
        if (!button) return;
        if (key === unitKey) {
            button.classList.add('active');
            button.setAttribute('aria-pressed', 'true');
        } else {
            button.classList.remove('active');
            button.setAttribute('aria-pressed', 'false');
        }
    });
}

function updateUnitAvailability() {
    const btnDbuv = document.getElementById('unitDbuv');
    const btnDbm = document.getElementById('unitDbm');
    const images = state.coverageData?.images || {};
    const hasDbuv = Boolean(images.dbuv?.image || state.coverageData?.image);
    const hasDbm = Boolean(images.dbm?.image);
    if (btnDbuv) {
        btnDbuv.disabled = !hasDbuv;
        btnDbuv.classList.toggle('disabled', !hasDbuv);
    }
    if (btnDbm) {
        btnDbm.disabled = !hasDbm;
        btnDbm.classList.toggle('disabled', !hasDbm);
        if (!hasDbm) {
            btnDbm.classList.remove('active');
            btnDbm.setAttribute('aria-pressed', 'false');
        }
    }
}

function setCoverageUnit(unitKey) {
    if (!state.coverageData) return;
    updateUnitAvailability();
    applyCoverageOverlay(unitKey);
    updateScaleReadout(unitKey);
    updateUnitButtons(unitKey);
    if (state.selectedRxIndex !== null) {
        const entry = state.rxEntries[state.selectedRxIndex];
        if (entry && entry.summary) {
            updateLinkSummary(entry.summary);
        }
    }
    renderRxList();
}

let txLocationAbortController = null;

function syncTxLocation(latLng) {
    if (!latLng) return;
    const payload = {
        latitude: latLng.lat(),
        longitude: latLng.lng(),
    };

    if (txLocationAbortController) {
        txLocationAbortController.abort();
    }
    txLocationAbortController = new AbortController();

    fetch('/tx-location', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: txLocationAbortController.signal,
    }).then((response) => {
        if (!response.ok) {
            throw new Error('Falha ao sincronizar localização da TX');
        }
        return response.json();
    }).then((data) => {
        if (!state.txData) {
            state.txData = {};
        }
        if (data.municipality !== undefined) {
            state.txData.txLocationName = data.municipality;
        }
        if (data.elevation !== undefined) {
            state.txData.txElevation = data.elevation;
        }
        updateTxSummary(state.txData);
    }).catch((error) => {
        if (error.name === 'AbortError') {
            return;
        }
        console.error(error);
    }).finally(() => {
        txLocationAbortController = null;
    });
}

function updateLossSummary(components, centerMetrics) {
    const summaries = components || {};
    const container = document.getElementById('lossSummary');
    if (!container) return;

    const keys = ['L_b0p', 'L_bd', 'L_bs', 'L_ba', 'L_b', 'L_b_corr'];
    keys.forEach((key) => {
        const el = document.getElementById(`loss-${key}`);
        if (!el) return;
        const item = summaries[key];
        if (!item) {
            el.textContent = '-';
            return;
        }
        const center = formatDbValue(item.center);
        if (item.min !== undefined && item.max !== undefined) {
            el.textContent = `${center} (${formatDbValue(item.min)} – ${formatDbValue(item.max)})`;
        } else {
            el.textContent = center;
        }
    });

    const pathInfo = document.getElementById('pathTypeInfo');
    if (pathInfo) {
        if (centerMetrics && centerMetrics.path_type) {
            const pathType = (centerMetrics.path_type || '').toString().toUpperCase();
            const lookup = {
                LOS: 'Trajeto predominante em linha de visada (LOS).',
                NLOS: 'Trajeto trans-horizonte com múltiplos mecanismos.',
                DIFFRACTION: 'Perdas dominadas por difração sobre o relevo.',
                TROPOSCATTER: 'Predomínio de espalhamento troposférico.',
            };
            pathInfo.textContent = lookup[pathType] || centerMetrics.path_type;
        } else {
            pathInfo.textContent = '';
        }
    }
}

function updateCenterMetrics(metrics) {
    const data = metrics || {};
    const setText = (id, value) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
        }
    };

    setText('centerLoss', formatDbValue(data.combined_loss_center_db));
    setText('centerPower', formatDbValue(data.received_power_center_dbm, 'dBm'));
    setText('centerField', formatDbValue(data.field_center_dbuv_m, 'dBµV/m'));
    setText('centerGain', formatDbValue(data.effective_gain_center_db));
    if (data.distance_center_km !== undefined && data.distance_center_km !== null) {
        setText('centerDistance', formatNumber(data.distance_center_km, ' km'));
    } else {
        setText('centerDistance', '-');
    }
    const pathEl = document.getElementById('centerPath');
    if (pathEl) {
        if (!data.path_type) {
            pathEl.textContent = '-';
        } else {
            const pathType = (data.path_type || '').toString().toUpperCase();
            const labelMap = {
                LOS: 'Linha de visada (LOS)',
                NLOS: 'Trans-horizonte (NLOS)',
                DIFFRACTION: 'Difração predominante',
                TROPOSCATTER: 'Espalhamento troposférico',
            };
            pathEl.textContent = labelMap[pathType] || data.path_type;
        }
    }
}

function ensureElevationService() {
    if (!state.elevationService) {
        state.elevationService = new google.maps.ElevationService();
    }
    return state.elevationService;
}

function clearCoverageOverlay() {
    if (state.coverageOverlay) {
        state.coverageOverlay.setMap(null);
        state.coverageOverlay = null;
    }
    if (state.radiusCircle) {
        state.radiusCircle.setMap(null);
        state.radiusCircle = null;
    }
}

function applyCoverageOverlay(unitKey = state.coverageUnit || 'dbuv') {
    if (!state.coverageData || !state.map) return;
    const response = state.coverageData;
    const images = response.images || {
        dbuv: {
            image: response.image || null,
            colorbar: response.colorbar || null,
            label: 'Campo elétrico [dBµV/m]',
            unit: 'dBµV/m',
        },
    };

    const entry = images[unitKey] || images.dbuv;
    if (!entry || !entry.image) return;

    clearCoverageOverlay();
    const bounds = response.bounds;
    if (!bounds) return;

    const overlayBounds = new google.maps.LatLngBounds(
        new google.maps.LatLng(bounds.south, bounds.west),
        new google.maps.LatLng(bounds.north, bounds.east)
    );

    const OverlayClass = ensureCoverageOverlayClass();
    const overlay = new OverlayClass(
        overlayBounds,
        `data:image/png;base64,${entry.image}`,
        state.overlayOpacity
    );
    overlay.setMap(state.map);
    state.coverageOverlay = overlay;
    state.coverageUnit = unitKey;

    const card = document.getElementById('colorbarCard');
    const img = document.getElementById('colorbarImage');
    const labelEl = document.getElementById('colorbarLabel');
    if (card && img) {
        if (entry.colorbar) {
            img.src = `data:image/png;base64,${entry.colorbar}`;
            card.hidden = false;
        } else {
            card.hidden = true;
        }
    }
    if (labelEl && entry.label) {
        labelEl.textContent = entry.label;
    }

    if (response.requested_radius_km && response.center) {
        const centerLatLng = new google.maps.LatLng(response.center.lat, response.center.lng);
        state.radiusCircle = new google.maps.Circle({
            map: state.map,
            center: centerLatLng,
            radius: response.requested_radius_km * 1000,
            strokeColor: '#0d6efd',
            strokeOpacity: 0.4,
            strokeWeight: 2,
            fillColor: '#0d6efd',
            fillOpacity: 0.1,
            clickable: false,
        });
        state.coverageRadiusKm = Number(response.requested_radius_km) || null;
    } else {
        state.coverageRadiusKm = null;
    }
}

function setOverlayOpacity(value) {
    state.overlayOpacity = value;
    if (state.coverageOverlay) {
        state.coverageOverlay.setOpacity(value);
    }
    if (state.radiusCircle) {
        state.radiusCircle.setOptions({ fillOpacity: Math.max(0.05, value / 6) });
    }
}

function findNearestFieldStrength(lat, lng, dict) {
    let best = null;
    let bestDist = Infinity;
    Object.entries(dict).forEach(([key, value]) => {
        const [lt, ln] = key.slice(1, -1).split(',').map(Number);
        const dist = Math.hypot(lat - lt, lng - ln);
        if (dist < bestDist) {
            bestDist = dist;
            best = value;
        }
    });
    return best;
}

function updateLinkSummary(summary) {
    document.getElementById('linkDistance').textContent = summary.distance || '-';
    document.getElementById('linkBearing').textContent = summary.bearing || '-';
    document.getElementById('linkField').textContent = formatFieldValue(summary);

    let elevationText = summary.elevation || '-';
    if (summary.obstacles && summary.obstacles !== '-' && summary.obstacles !== 'Nenhum') {
        elevationText = `${elevationText} | Obst.: ${summary.obstacles}`;
    }
    document.getElementById('linkElevation').textContent = elevationText;
}

function highlightRxEntry(index) {
    state.rxEntries.forEach((entry, idx) => {
        entry.marker.setIcon(idx === index ? entry.icons.selected : entry.icons.default);
    });
}

function updateLinkVisuals(entry) {
    if (state.linkLine) {
        state.linkLine.setMap(null);
    }
    state.linkLine = new google.maps.Polyline({
        map: state.map,
        path: [state.txCoords, entry.marker.getPosition()],
        strokeColor: '#0d6efd',
        strokeOpacity: 0.9,
        strokeWeight: 3,
    });
    if (entry.summary) {
        updateLinkSummary(entry.summary);
    }
}

function selectRx(index) {
    state.selectedRxIndex = index;
    highlightRxEntry(index);
    const entry = state.rxEntries[index];
    updateLinkVisuals(entry);
    document.getElementById('btnGenerateProfile').disabled = false;
}

function removeRx(index) {
    const [entry] = state.rxEntries.splice(index, 1);
    if (entry) {
        entry.marker.setMap(null);
    }
    if (state.linkLine) {
        state.linkLine.setMap(null);
        state.linkLine = null;
    }
    state.selectedRxIndex = null;
    updateLinkSummary({});
    renderRxList();
}

function clearReceivers() {
    state.rxEntries.forEach((entry) => entry.marker.setMap(null));
    state.rxEntries = [];
    state.selectedRxIndex = null;
    if (state.linkLine) {
        state.linkLine.setMap(null);
        state.linkLine = null;
    }
    updateLinkSummary({});
    renderRxList();
    document.getElementById('btnGenerateProfile').disabled = true;
}

function renderRxList() {
    const container = document.getElementById('rxList');
    container.innerHTML = '';
    if (!state.rxEntries.length) {
        container.innerHTML = '<li class="rx-empty">Nenhum ponto RX selecionado.</li>';
        return;
    }

    state.rxEntries.forEach((entry, idx) => {
        const li = document.createElement('li');
        li.className = `rx-item${idx === state.selectedRxIndex ? ' selected' : ''}`;
        const title = document.createElement('div');
        title.className = 'rx-title';
        title.textContent = `RX ${idx + 1}`;

        const details = document.createElement('div');
        details.className = 'rx-details';
        const summary = entry.summary || {};
        details.innerHTML = `
            <span>${summary.distance || '-'}</span>
            <span>${formatFieldValue(summary)}</span>
            <span>${summary.obstacles || '-'}</span>
            <span>${summary.elevation || '-'}</span>
        `;

        const actions = document.createElement('div');
        actions.className = 'rx-actions';
        const focusBtn = document.createElement('button');
        focusBtn.type = 'button';
        focusBtn.textContent = 'Focar';
        focusBtn.className = 'btn btn-sm btn-outline-primary';
        focusBtn.onclick = (event) => {
            event.stopPropagation();
            state.map.panTo(entry.marker.getPosition());
            state.map.setZoom(Math.max(state.map.getZoom(), 11));
            selectRx(idx);
        };

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.textContent = 'Remover';
        removeBtn.className = 'btn btn-sm btn-link text-danger';
        removeBtn.onclick = (event) => {
            event.stopPropagation();
            removeRx(idx);
        };

        const profileBtn = document.createElement('button');
        profileBtn.type = 'button';
        profileBtn.textContent = 'Perfil';
        profileBtn.className = 'btn btn-sm btn-outline-success';
        profileBtn.onclick = (event) => {
            event.stopPropagation();
            selectRx(idx);
            generateProfile();
        };

        actions.appendChild(focusBtn);
        actions.appendChild(profileBtn);
        actions.appendChild(removeBtn);

        li.appendChild(title);
        li.appendChild(details);
        li.appendChild(actions);
        li.onclick = (event) => {
            if (event.target === removeBtn || event.target === focusBtn || event.target === profileBtn) return;
            selectRx(idx);
        };
        container.appendChild(li);
    });
}

function getElevation(position) {
    ensureElevationService();
    return new Promise((resolve) => {
        state.elevationService.getElevationForLocations({ locations: [position] }, (results, status) => {
            if (status === 'OK' && results && results.length) {
                resolve(results[0].elevation);
            } else {
                resolve(null);
            }
        });
    });
}

function computeReceiverSummary(position) {
    const distanceMeters = google.maps.geometry.spherical.computeDistanceBetween(state.txCoords, position);
    const bearing = google.maps.geometry.spherical.computeHeading(state.txCoords, position);
    const summary = {
        distance: `${(distanceMeters / 1000).toFixed(2)} km`,
        bearing: `${bearing.toFixed(1)}°`,
    };

    const radiusLimitMeters = state.coverageRadiusKm ? state.coverageRadiusKm * 1000 : null;
    const insideCoverage = radiusLimitMeters === null || distanceMeters <= radiusLimitMeters + 20;
    summary.insideCoverage = insideCoverage;
    summary.field_dbuv = undefined;
    summary.field_dbm = undefined;
    summary.obstacles = summary.obstacles || '-';

    const dictDbuv = state.signalLevelDict?.dbuv || {};
    const dictDbm = state.signalLevelDict?.dbm || {};

    if (insideCoverage) {
        const fieldDbuv = findNearestFieldStrength(position.lat(), position.lng(), dictDbuv);
        if (fieldDbuv !== null && fieldDbuv !== undefined) {
            summary.field_dbuv = Number(fieldDbuv);
        }
        const fieldDbm = findNearestFieldStrength(position.lat(), position.lng(), dictDbm);
        if (fieldDbm !== null && fieldDbm !== undefined) {
            summary.field_dbm = Number(fieldDbm);
        }
    }
    summary.pendingField = insideCoverage && summary.field_dbuv === undefined && summary.field_dbm === undefined;

    return getElevation(position).then((elevation) => {
        if (elevation !== null) {
            summary.elevation = `${elevation.toFixed(1)} m`;
        }
        return summary;
    });
}

function formatFieldValue(summary) {
    if (!summary) return '-';
    const unitKey = state.coverageUnit || 'dbuv';
    if (unitKey === 'dbm') {
        if (summary.field_dbm !== undefined) {
            return `${summary.field_dbm.toFixed(1)} dBm`;
        }
    } else {
        if (summary.field_dbuv !== undefined) {
            return `${summary.field_dbuv.toFixed(1)} dBµV/m`;
        }
    }
    if (summary.insideCoverage === false) {
        return 'Fora da área';
    }
    return summary.pendingField ? 'Em cálculo' : '-';
}

function createRxMarker(position) {
    const defaultIcon = {
        path: google.maps.SymbolPath.CIRCLE,
        fillColor: '#6610f2',
        fillOpacity: 0.85,
        scale: 7,
        strokeColor: '#fff',
        strokeWeight: 2,
    };
    const selectedIcon = {
        path: google.maps.SymbolPath.CIRCLE,
        fillColor: '#d63384',
        fillOpacity: 1,
        scale: 8,
        strokeColor: '#fff',
        strokeWeight: 2,
    };

    const marker = new google.maps.Marker({
        position,
        map: state.map,
        icon: defaultIcon,
        title: `RX ${state.rxEntries.length + 1}`,
    });

    const entry = {
        marker,
        summary: null,
        icons: { default: defaultIcon, selected: selectedIcon },
    };

    marker.addListener('click', () => {
        const index = state.rxEntries.indexOf(entry);
        if (index >= 0) {
            selectRx(index);
        }
    });

    state.rxEntries.push(entry);
    computeReceiverSummary(position).then((summary) => {
        entry.summary = summary;
        entry.pendingField = summary.pendingField;
        if (state.selectedRxIndex === state.rxEntries.indexOf(entry)) {
            updateLinkSummary(summary);
        }
        renderRxList();
    });
    renderRxList();
    selectRx(state.rxEntries.length - 1);
}

function handleMapClick(event) {
    if (!state.txCoords) return;
    createRxMarker(event.latLng);
}

function setTxCoords(latLng, { pan = false } = {}) {
    const prevCoords = state.txCoords
        ? new google.maps.LatLng(state.txCoords.lat(), state.txCoords.lng())
        : null;
    state.txCoords = latLng;
    if (state.txMarker) {
        state.txMarker.setPosition(latLng);
    }
    if (pan) {
        state.map.panTo(latLng);
    }
    if (state.txData) {
        state.txData.latitude = latLng.lat();
        state.txData.longitude = latLng.lng();
        updateTxSummary(state.txData);
    }
    const distanceChanged = prevCoords
        ? google.maps.geometry.spherical.computeDistanceBetween(prevCoords, latLng)
        : Number.POSITIVE_INFINITY;
    if (!prevCoords || distanceChanged > 0.5) {
        syncTxLocation(latLng);
    }
    state.rxEntries.forEach((entry, idx) => {
        if (entry.summary) {
            computeReceiverSummary(entry.marker.getPosition()).then((summary) => {
                entry.summary = summary;
                if (idx === state.selectedRxIndex) {
                    updateLinkSummary(summary);
                }
                renderRxList();
            });
        }
    });
}

function handleTxDragEnd(event) {
    const position = event.latLng;
    setTxCoords(position, { pan: false });
    showToast('Posição da TX atualizada. Gere a cobertura novamente.', false);
    markCoverageStale('Posição da TX alterada. Gere a cobertura novamente.');
}

function saveTilt(value) {
    if (state.pendingTiltTimeout) {
        clearTimeout(state.pendingTiltTimeout);
    }
    state.pendingTiltTimeout = setTimeout(() => {
        fetch('/update-tilt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tilt: value }),
        }).then((response) => {
            if (!response.ok) {
                throw new Error('Falha ao atualizar tilt');
            }
            return response.json();
        }).then(() => {
            if (state.txData) {
                state.txData.antennaTilt = Number(value);
            }
            showToast('Tilt atualizado. Gere a cobertura novamente.');
            markCoverageStale('Tilt alterado. Gere a cobertura novamente.');
        }).catch((error) => {
            console.error(error);
            showToast('Erro ao atualizar tilt', true);
        });
    }, 350);
}

function generateCoverage() {
    if (!state.txCoords) return;
    const radiusKm = Number(document.getElementById('radiusInput').value) || 0;
    const minField = document.getElementById('minField').value;
    const maxField = document.getElementById('maxField').value;

    const payload = {
        radius: radiusKm,
        minSignalLevel: minField || null,
        maxSignalLevel: maxField || null,
        customCenter: { lat: state.txCoords.lat(), lng: state.txCoords.lng() },
    };

    setCoverageLoading(true);

    fetch('/calculate-coverage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then((response) => {
        if (!response.ok) {
            throw new Error('Falha ao gerar cobertura');
        }
        return response.json();
    }).then((data) => {
        state.coverageData = data;
        state.coverageRadiusKm = Number(data.requested_radius_km) || null;
        state.signalLevelDict = {
            dbuv: data.signal_level_dict || {},
            dbm: data.signal_level_dict_dbm || {},
        };
        state.lossComponents = data.loss_components || null;
        state.centerMetrics = data.center_metrics || null;

        if (!state.txData) {
            state.txData = {};
        }
        if (data.tx_location_name !== undefined) {
            state.txData.txLocationName = data.tx_location_name;
        }
        if (data.tx_site_elevation !== undefined) {
            state.txData.txElevation = data.tx_site_elevation;
        }
        if (data.climate_updated_at) {
            state.txData.climateUpdatedAt = data.climate_updated_at;
        }

        if (data.center) {
            const centerLatLng = new google.maps.LatLng(data.center.lat, data.center.lng);
            setTxCoords(centerLatLng, { pan: false });
        } else {
            updateTxSummary(state.txData);
        }

        const defaultUnit = (data.scale && data.scale.default_unit) || 'dbuv';
        state.coverageUnit = defaultUnit;
        setCoverageUnit(defaultUnit);
        updateGainSummary(data.gain_components || null);
        updateLossSummary(state.lossComponents, state.centerMetrics);
        updateCenterMetrics(state.centerMetrics);

        if (data.location_status) {
            setCoverageStatus(data.location_status);
        } else {
            clearCoverageStatus();
        }

        const recomputePromises = state.rxEntries.map((entry, idx) =>
            computeReceiverSummary(entry.marker.getPosition()).then((summary) => {
                entry.summary = summary;
                if (idx === state.selectedRxIndex) {
                    updateLinkSummary(summary);
                }
            })
        );
        Promise.all(recomputePromises).finally(() => {
            renderRxList();
        });
        showToast('Cobertura atualizada com sucesso');
    }).catch((error) => {
        console.error(error);
        showToast('Não foi possível gerar a cobertura', true);
    }).finally(() => {
        setCoverageLoading(false);
    });
}

function generateProfile() {
    if (state.selectedRxIndex === null) {
        showToast('Selecione um RX na lista', true);
        return;
    }
    const entry = state.rxEntries[state.selectedRxIndex];
    if (!entry || !state.txCoords) return;

    const tx = state.txCoords;
    const rx = entry.marker.getPosition();
    const payload = {
        path: [
            { lat: tx.lat(), lng: tx.lng() },
            { lat: rx.lat(), lng: rx.lng() },
        ],
    };

    fetch('/gerar_img_perfil', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then((response) => {
        if (!response.ok) {
            throw new Error('Falha ao gerar perfil');
        }
        return response.json();
    }).then((data) => {
        const img = document.getElementById('profileImage');
        img.src = `data:image/png;base64,${data.image}`;

        if (!entry.summary) {
            entry.summary = {};
        }
        if (data.field_dbuv !== undefined) {
            entry.summary.field_dbuv = Number(data.field_dbuv);
            entry.summary.pendingField = false;
        }
        if (Array.isArray(data.obstacle_distances_km)) {
            entry.summary.obstacles = data.obstacle_distances_km.length
                ? data.obstacle_distances_km.slice(0, 6).map((dist) => `${Number(dist).toFixed(2)} km`).join(', ')
                : 'Nenhum';
        }
        if (data.received_power_dbm !== undefined) {
            entry.summary.field_dbm = Number(data.received_power_dbm);
        }
        if (data.tx_gain_dbi !== undefined) {
            entry.summary.txGain = `${Number(data.tx_gain_dbi).toFixed(2)} dBi`;
        }
        renderRxList();
        updateLinkSummary(entry.summary);

        const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('profileModal'));
        modal.show();
    }).catch((error) => {
        console.error(error);
        showToast('Não foi possível gerar o perfil', true);
    });
}

function initControls() {
    document.getElementById('radiusInput').addEventListener('input', updateRadiusLabel);
    document.getElementById('btnGenerateCoverage').addEventListener('click', generateCoverage);
    document.getElementById('btnGenerateProfile').addEventListener('click', generateProfile);
    document.getElementById('btnClearRx').addEventListener('click', clearReceivers);

    const overlayInput = document.getElementById('overlayOpacity');
    const overlayLabel = document.getElementById('overlayOpacityValue');
    overlayInput.addEventListener('input', (event) => {
        const value = Number(event.target.value);
        overlayLabel.textContent = value.toFixed(2);
        setOverlayOpacity(value);
    });
    overlayInput.value = OVERLAY_DEFAULT_OPACITY;
    overlayLabel.textContent = OVERLAY_DEFAULT_OPACITY.toFixed(2);

    const tiltControl = document.getElementById('tiltControl');
    tiltControl.addEventListener('input', (event) => {
        updateTiltLabel(event.target.value);
    });
    tiltControl.addEventListener('change', (event) => {
        saveTilt(event.target.value);
    });

    const unitDbuv = document.getElementById('unitDbuv');
    if (unitDbuv) {
        unitDbuv.addEventListener('click', () => setCoverageUnit('dbuv'));
    }
    const unitDbm = document.getElementById('unitDbm');
    if (unitDbm) {
        unitDbm.addEventListener('click', () => setCoverageUnit('dbm'));
    }

    updateRadiusLabel();
}

function initCoverageMap() {
    fetch('/carregar-dados')
        .then((response) => response.json())
        .then((data) => {
            state.txData = { ...data };
            const txLatLng = new google.maps.LatLng(data.latitude, data.longitude);
            state.txCoords = txLatLng;
            updateTxSummary(data);

            state.map = new google.maps.Map(document.getElementById('coverageMap'), {
                center: txLatLng,
                zoom: 9,
                mapTypeId: 'terrain',
                gestureHandling: 'greedy',
            });

            state.txMarker = new google.maps.Marker({
                position: txLatLng,
                map: state.map,
                title: 'Transmissor',
                draggable: true,
                icon: {
                    url: 'https://maps.gstatic.com/mapfiles/ms2/micons/red-dot.png',
                },
            });
            state.txMarker.addListener('dragend', handleTxDragEnd);

            state.map.addListener('click', handleMapClick);

            initControls();
            updateUnitButtons(state.coverageUnit || 'dbuv');
            ensureElevationService();
        })
        .catch((error) => {
            console.error('Erro ao carregar dados do usuário', error);
            showToast('Não foi possível carregar os dados iniciais', true);
        });
}

window.initCoverageMap = initCoverageMap;
