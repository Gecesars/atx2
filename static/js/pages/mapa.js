const state = {
    map: null,
    txMarker: null,
    rxMarker: null,
    linkLine: null,
    coverageOverlay: null,
    elevationService: null,
    txCoords: null,
    coverageData: null,
    pendingTiltTimeout: null,
};

function formatNumber(value, suffix = '') {
    if (value === undefined || value === null || Number.isNaN(value)) {
        return '-';
    }
    return `${value.toFixed(2)}${suffix}`;
}

function formatDb(value) {
    if (value === undefined || value === null || Number.isNaN(value)) {
        return '-';
    }
    return `${value.toFixed(2)} dB`;
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
    document.getElementById('txFreq').textContent = data.frequency ? `${data.frequency.toFixed(2)} MHz` : '-';
    document.getElementById('txModel').textContent = data.propagationModel || '-';
    updateTiltLabel(data.antennaTilt || 0);
    document.getElementById('tiltControl').value = data.antennaTilt ?? 0;
}

function updateGainSummary(gainComponents, scale) {
    if (!gainComponents) {
        document.getElementById('gainBase').textContent = '-';
        document.getElementById('gainHorizontal').textContent = '-';
        document.getElementById('gainVertical').textContent = '-';
        document.getElementById('fieldScale').textContent = '-';
        return;
    }
    document.getElementById('gainBase').textContent = formatDb(gainComponents.base_gain_dbi || 0);
    if (gainComponents.horizontal_adjustment_db_min !== undefined) {
        const min = formatDb(gainComponents.horizontal_adjustment_db_min);
        const max = formatDb(gainComponents.horizontal_adjustment_db_max);
        document.getElementById('gainHorizontal').textContent = `${min} / ${max}`;
    }
    document.getElementById('gainVertical').textContent = formatDb(gainComponents.vertical_adjustment_db);
    if (scale) {
        document.getElementById('fieldScale').textContent = `${formatNumber(scale.min)} – ${formatNumber(scale.max)} dBµV/m`;
    }
}

function clearCoverageOverlay() {
    if (state.coverageOverlay) {
        state.coverageOverlay.setMap(null);
        state.coverageOverlay = null;
    }
}

function applyCoverageOverlay(response) {
    clearCoverageOverlay();
    const bounds = response.bounds;
    if (!bounds) return;
    const overlayBounds = new google.maps.LatLngBounds(
        new google.maps.LatLng(bounds.south, bounds.west),
        new google.maps.LatLng(bounds.north, bounds.east)
    );
    const overlay = new google.maps.GroundOverlay(
        `data:image/png;base64,${response.image}`,
        overlayBounds,
        { opacity: 0.9 }
    );
    overlay.setMap(state.map);
    state.coverageOverlay = overlay;

    if (response.colorbar) {
        const card = document.getElementById('colorbarCard');
        const img = document.getElementById('colorbarImage');
        img.src = `data:image/png;base64,${response.colorbar}`;
        card.hidden = false;
    }
}

function updateLinkSummary(summary) {
    document.getElementById('linkDistance').textContent = summary.distance || '-';
    document.getElementById('linkBearing').textContent = summary.bearing || '-';
    document.getElementById('linkField').textContent = summary.field || '-';
    document.getElementById('linkElevation').textContent = summary.elevation || '-';
}

function handleMapClick(event) {
    const position = event.latLng;
    if (!state.txCoords) return;

    if (state.rxMarker) {
        state.rxMarker.setMap(null);
    }

    state.rxMarker = new google.maps.Marker({
        position,
        map: state.map,
        title: 'Receptor',
        icon: {
            url: 'https://maps.gstatic.com/mapfiles/api-3/images/spotlight-poi2.png',
            scaledSize: new google.maps.Size(27, 43)
        }
    });

    if (state.linkLine) {
        state.linkLine.setMap(null);
    }

    state.linkLine = new google.maps.Polyline({
        map: state.map,
        path: [state.txCoords, position],
        strokeColor: '#0d6efd',
        strokeOpacity: 0.9,
        strokeWeight: 3
    });

    const distanceMeters = google.maps.geometry.spherical.computeDistanceBetween(state.txCoords, position);
    const bearing = google.maps.geometry.spherical.computeHeading(state.txCoords, position);
    const summary = {
        distance: `${(distanceMeters / 1000).toFixed(2)} km`,
        bearing: `${bearing.toFixed(1)}°`,
    };

    if (state.coverageData && state.coverageData.signal_level_dict) {
        const field = findNearestFieldStrength(position.lat(), position.lng(), state.coverageData.signal_level_dict);
        if (field !== null) {
            summary.field = `${field.toFixed(1)} dBµV/m`;
        }
    }

    if (!state.elevationService) {
        state.elevationService = new google.maps.ElevationService();
    }

    state.elevationService.getElevationForLocations({ locations: [position] }, (results, status) => {
        if (status === 'OK' && results && results.length) {
            summary.elevation = `${results[0].elevation.toFixed(1)} m`; 
        }
        updateLinkSummary(summary);
    });

    document.getElementById('btnGenerateProfile').disabled = false;
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

function generateCoverage() {
    if (!state.txCoords) return;
    const radiusKm = Number(document.getElementById('radiusInput').value) || 0;
    const minField = document.getElementById('minField').value;
    const maxField = document.getElementById('maxField').value;

    const payload = {
        radius: radiusKm,
        minSignalLevel: minField || null,
        maxSignalLevel: maxField || null,
    };

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
        applyCoverageOverlay(data);
        updateGainSummary(data.gain_components, data.scale);
        showMapToast('Cobertura atualizada com sucesso');
    }).catch((error) => {
        console.error(error);
        showMapToast('Não foi possível gerar a cobertura', true);
    });
}

function showMapToast(message, isError = false) {
    const card = document.getElementById('mapTooltip');
    if (!card) return;
    card.innerHTML = `<h4>${isError ? 'Atenção' : 'Cobertura'}</h4><p>${message}</p>`;
    card.hidden = false;
    setTimeout(() => {
        card.hidden = true;
    }, 3500);
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
            showMapToast('Tilt atualizado');
        }).catch((error) => {
            console.error(error);
            showMapToast('Erro ao atualizar tilt', true);
        });
    }, 350);
}

function generateProfile() {
    if (!state.rxMarker || !state.txCoords) {
        showMapToast('Selecione um ponto RX no mapa', true);
        return;
    }
    const tx = state.txCoords;
    const rx = state.rxMarker.getPosition();
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
        const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('profileModal'));
        modal.show();
    }).catch((error) => {
        console.error(error);
        showMapToast('Não foi possível gerar o perfil', true);
    });
}

function initControls() {
    document.getElementById('radiusInput').addEventListener('input', updateRadiusLabel);
    document.getElementById('btnGenerateCoverage').addEventListener('click', generateCoverage);
    document.getElementById('btnGenerateProfile').addEventListener('click', generateProfile);

    const tiltControl = document.getElementById('tiltControl');
    tiltControl.addEventListener('input', (event) => {
        updateTiltLabel(event.target.value);
    });
    tiltControl.addEventListener('change', (event) => {
        saveTilt(event.target.value);
    });

    updateRadiusLabel();
}

function initCoverageMap() {
    fetch('/carregar-dados')
        .then((response) => response.json())
        .then((data) => {
            state.txCoords = new google.maps.LatLng(data.latitude, data.longitude);
            updateTxSummary(data);

            state.map = new google.maps.Map(document.getElementById('coverageMap'), {
                center: state.txCoords,
                zoom: 9,
                mapTypeId: 'terrain',
                gestureHandling: 'greedy',
            });

            state.txMarker = new google.maps.Marker({
                position: state.txCoords,
                map: state.map,
                title: 'Transmissor',
                icon: {
                    url: 'https://maps.gstatic.com/mapfiles/ms2/micons/red-dot.png',
                },
            });

            state.map.addListener('click', handleMapClick);

            initControls();
        })
        .catch((error) => {
            console.error('Erro ao carregar dados do usuário', error);
            showMapToast('Não foi possível carregar os dados iniciais', true);
        });
}

window.initCoverageMap = initCoverageMap;
