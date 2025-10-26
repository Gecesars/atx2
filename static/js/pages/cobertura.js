(function () {
    let map;
    let marker;
    const modals = {};
    const modalFactory = window.bootstrap && window.bootstrap.Modal;

    function initModals() {
        const modalElements = {
            map: document.getElementById('mapModal'),
            coordinates: document.getElementById('coordinatesModal'),
            success: document.getElementById('successModal'),
            error: document.getElementById('errorModal'),
        };

        Object.entries(modalElements).forEach(([key, element]) => {
            if (element) {
                modals[key] = modalFactory ? modalFactory.getOrCreateInstance(element) : createFallbackModal(element);
            }
        });

        const mapElement = modalElements.map;
        if (mapElement && modalFactory) {
            mapElement.addEventListener('shown.bs.modal', () => {
                if (map) {
                    google.maps.event.trigger(map, 'resize');
                }
            });
        }
    }

    async function carregarDadosUsuario() {
        try {
            const response = await fetch('/carregar-dados');
            if (!response.ok) {
                throw new Error('Falha ao carregar dados do usuário');
            }
            const data = await response.json();
            Object.entries(data).forEach(([key, value]) => {
                const input = document.getElementById(key);
                if (input) {
                    input.value = value ?? '';
                }
            });
            if (data.latitude && data.longitude) {
                document.getElementById('coordinates').value = `Latitude: ${data.latitude}, Longitude: ${data.longitude}`;
            }
            if (data.nomeUsuario) {
                const userName = document.getElementById('userName');
                if (userName) {
                    userName.textContent = data.nomeUsuario;
                }
            }
        } catch (error) {
            console.error(error);
        }
    }

    function updateDMS(decimalFieldId, degreesFieldId, minutesFieldId, secondsFieldId, directionFieldId) {
        const decimalValue = parseFloat(document.getElementById(decimalFieldId).value);
        if (Number.isNaN(decimalValue)) {
            return;
        }
        const sign = Math.sign(decimalValue);
        const absoluteValue = Math.abs(decimalValue);

        let degrees = Math.floor(absoluteValue);
        const fractionalPart = absoluteValue - degrees;
        let minutes = Math.floor(fractionalPart * 60);
        const seconds = Math.round((fractionalPart * 3600) % 60);

        if (minutes === 60) {
            degrees++;
            minutes = 0;
        }

        document.getElementById(degreesFieldId).value = degrees * sign;
        document.getElementById(minutesFieldId).value = minutes;
        document.getElementById(secondsFieldId).value = seconds;
        document.getElementById(directionFieldId).value = sign >= 0 ? 'N' : 'S';
    }

    function updateDecimal(degreesFieldId, minutesFieldId, secondsFieldId, directionFieldId, decimalFieldId) {
        const degrees = parseFloat(document.getElementById(degreesFieldId).value) || 0;
        const minutes = parseFloat(document.getElementById(minutesFieldId).value) || 0;
        const seconds = parseFloat(document.getElementById(secondsFieldId).value) || 0;
        const directionValue = document.getElementById(directionFieldId).value;
        const direction = directionValue === 'N' || directionValue === 'E' ? 1 : -1;
        const decimalValue = degrees + (minutes / 60) + (seconds / 3600);
        document.getElementById(decimalFieldId).value = (decimalValue * direction).toFixed(6);
    }

    function placeMarkerAndPanTo(latLng) {
        if (marker) {
            marker.setMap(null);
        }
        marker = window.marker = new google.maps.Marker({
            position: latLng,
            map,
        });
        map.panTo(latLng);

        const latitude = latLng.lat().toFixed(6);
        const longitude = latLng.lng().toFixed(6);
        document.getElementById('coordinates').value = `Latitude: ${latitude}, Longitude: ${longitude}`;

        const coverageButton = document.getElementById('generateCoverageButton');
        if (coverageButton) {
            coverageButton.disabled = false;
        }
    }

    function saveCoordinates() {
        if (!marker) {
            alert('Por favor, selecione um ponto no mapa.');
            return;
        }
        const latitude = marker.getPosition().lat().toFixed(6);
        const longitude = marker.getPosition().lng().toFixed(6);
        document.getElementById('coordinates').value = `Latitude: ${latitude}, Longitude: ${longitude}`;
        const coverageButton = document.getElementById('generateCoverageButton');
        if (coverageButton) {
            coverageButton.disabled = false;
        }
        modals.map?.hide();
    }

    function saveManualCoordinates() {
        const latitudeDecimal = document.getElementById('latitudeDecimal').value;
        const latitudeDirection = document.getElementById('latitudeDirection').value;
        const longitudeDecimal = document.getElementById('longitudeDecimal').value;
        const longitudeDirection = document.getElementById('longitudeDirection').value;

        if (latitudeDecimal && latitudeDirection && longitudeDecimal && longitudeDirection) {
            const latitude = `${latitudeDecimal} ${latitudeDirection}`;
            const longitude = `${longitudeDecimal} ${longitudeDirection}`;
            document.getElementById('coordinates').value = `Latitude: ${latitude}, Longitude: ${longitude}`;
            const coverageButton = document.getElementById('generateCoverageButton');
            if (coverageButton) {
                coverageButton.disabled = false;
            }
            modals.coordinates?.hide();
        } else {
            alert('Por favor, preencha todas as coordenadas.');
        }
    }

    function openMapModal() {
        modals.map?.show();
    }

    function openManualCoordinatesModal() {
        modals.coordinates?.show();
    }

    function fecharModalMapa() {
        modals.map?.hide();
    }

    async function submitForm() {
        const form = document.getElementById('coberturaForm');
        if (!form) {
            return;
        }

        const formData = new FormData(form);
        const coordinates = document.getElementById('coordinates').value;
        const [latitudePart, longitudePart] = coordinates.replace('Latitude: ', '').replace('Longitude: ', '').split(', ');

        const [latitudeValue, latitudeDirection] = (latitudePart || '').split(' ');
        const [longitudeValue, longitudeDirection] = (longitudePart || '').split(' ');

        const payload = {
            propagationModel: formData.get('propagationModel'),
            Total_loss: parseFloat(formData.get('Total_loss')),
            antennaGain: parseFloat(formData.get('antennaGain')),
            towerHeight: parseFloat(formData.get('towerHeight')),
            rxHeight: parseFloat(formData.get('rxHeight')),
            rxGain: parseFloat(formData.get('rxGain')),
            transmissionPower: parseFloat(formData.get('transmissionPower')),
            frequency: parseFloat(formData.get('frequency')),
            service: formData.get('serviceType'),
            latitude: latitudeValue,
            longitude: longitudeValue,
        };

        const tiltField = formData.get('antennaTilt');
        if (tiltField !== null && tiltField !== undefined && tiltField !== '') {
            payload.antennaTilt = parseFloat(tiltField);
        }

        if (latitudeDirection === 'S') {
            payload.latitude = `-${latitudeValue}`;
        }
        if (longitudeDirection === 'W') {
            payload.longitude = `-${longitudeValue}`;
        }

        try {
            await axios.post('/salvar-dados', payload);
            modals.success?.show();
        } catch (error) {
            console.error(error);
            modals.error?.show();
        }
    }

    window.initMap = function () {
        map = window.map = new google.maps.Map(document.getElementById('map'), {
            center: { lat: -14.235004, lng: -51.92528 },
            zoom: 4,
            gestureHandling: 'greedy',
        });

        map.addListener('click', (event) => {
            placeMarkerAndPanTo(event.latLng);
        });
    };

    function askForCoordinates() {
        const wantsMap = confirm('Deseja posicionar a torre clicando no mapa? Se escolher "Cancelar", você poderá inserir as coordenadas manualmente.');
        if (wantsMap) {
            openMapModal();
        } else {
            openManualCoordinatesModal();
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        initModals();
        carregarDadosUsuario();

        const askCoordinatesBtn = document.getElementById('askCoordinatesBtn');
        if (askCoordinatesBtn) {
            askCoordinatesBtn.addEventListener('click', askForCoordinates);
        }

        const openManualCoordinatesBtn = document.getElementById('openManualCoordinatesBtn');
        if (openManualCoordinatesBtn) {
            openManualCoordinatesBtn.addEventListener('click', openManualCoordinatesModal);
        }

        const saveMapPointBtn = document.getElementById('saveCoordinatesBtn');
        if (saveMapPointBtn) {
            saveMapPointBtn.addEventListener('click', saveCoordinates);
        }

        const saveManualCoordinatesBtn = document.getElementById('saveManualCoordinatesBtn');
        if (saveManualCoordinatesBtn) {
            saveManualCoordinatesBtn.addEventListener('click', saveManualCoordinates);
        }

        const closeMapModalBtn = document.getElementById('closeMapModalBtn');
        if (closeMapModalBtn) {
            closeMapModalBtn.addEventListener('click', fecharModalMapa);
        }

        const saveFormBtn = document.getElementById('saveCoverageBtn');
        if (saveFormBtn) {
            saveFormBtn.addEventListener('click', submitForm);
        }

        const generateCoverageBtn = document.getElementById('generateCoverageButton');
        if (generateCoverageBtn) {
            generateCoverageBtn.addEventListener('click', submitForm);
        }

        const refreshDataBtn = document.getElementById('refreshDataBtn');
        if (refreshDataBtn) {
            refreshDataBtn.addEventListener('click', carregarDadosUsuario);
        }

        const backButton = document.getElementById('backToHomeBtn');
        if (backButton) {
            backButton.addEventListener('click', () => {
                window.location.href = '/home';
            });
        }
    });

    window.coverageForm = {
        updateDMS,
        updateDecimal,
    };

    // exposição de funções para compatibilidade com scripts existentes
    window.carregarDadosUsuario = carregarDadosUsuario;
    window.updateDMS = updateDMS;
    window.updateDecimal = updateDecimal;
    window.saveCoordinates = saveCoordinates;
    window.saveManualCoordinates = saveManualCoordinates;
    window.submitForm = submitForm;
    window.askForCoordinates = askForCoordinates;
    window.fecharModalMapa = fecharModalMapa;
    window.placeMarkerAndPanTo = placeMarkerAndPanTo;

    function createFallbackModal(element) {
        return {
            show() {
                element.classList.add('show');
                element.style.display = 'block';
                element.removeAttribute('aria-hidden');
            },
            hide() {
                element.classList.remove('show');
                element.style.display = 'none';
                element.setAttribute('aria-hidden', 'true');
            },
        };
    }
})();
