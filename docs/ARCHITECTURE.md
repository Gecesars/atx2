# ATX Coverage – Arquitetura e Fluxos (v2)

## Visão Geral

A aplicação ATX Coverage foi reorganizada para separar claramente backend, camada visual e assets. O backend Flask roda sob `gunicorn` (gerenciado por systemd) e expõe APIs para cadastro de usuários, controle de padrões de antena, geração de mapas de cobertura em dBµV/m e perfis profissionais. O frontend utiliza um layout comum, CSS/JS modulados por página e integrações diretas com Google Maps.

## Backend

### Fábrica da aplicação e serviço
- **`app_core/__init__.py`**: faz `load_dotenv`, lê variáveis críticas (secret key, banco, Google Maps, diretórios), inicializa `SQLAlchemy`, `LoginManager`, `Flask-Migrate` e `CORS`, registra o blueprint `app_core.routes.ui` e injeta `current_year` nos templates.
- **`app3.py`**: mantém compatibilidade com Procfile/Heroku e define limites de threads BLAS antes de executar a aplicação.
- **`/etc/systemd/system/atxcover.service`**: executa `gunicorn` a partir do virtualenv `.venv`, lê `.env` via `EnvironmentFile`, usa timeout ampliado (180s) e se reinicia automaticamente se algo falhar.

### Blueprint `app_core.routes.ui`
- **Autenticação & shell**: rotas públicas (`inicio`, `index`, `register`) e protegidas (`home`, `logout`) com Flask-Login.
- **Antena**:
  - Upload e parsing de arquivos `.pat` por `parse_pat` (E/Emax horizontal/vertical).
  - Geração/salvamento de diagramas com commit no modelo `User`.
- **Cobertura (`/calculate-coverage`)**:
  - Ajusta o centro usando regressões (`adjust_center`) e consulta a topografia SRTM (`pycraf.pathprof.height_map_data`).
  - Calcula perdas por `atten_map_fast` e separa o ganho da antena em duas componentes: horizontal (E/Emax rotacionado de acordo com a direção) e vertical (E/Emax na linha do horizonte com tilt aplicado).
  - Converte potência recebida para campo elétrico (`dBµV/m`), aplica autoescala por percentis, mascara fora do raio e retorna imagem base64, colorbar, limites, dicionário de pontos, escala e `gain_components` (base, horizontal, vertical, padrões lineares).
  - Desde esta versão, a resposta agrega `loss_components` (L_b0p, L_bd, L_bs, L_ba, L_b, L_b_corr) com min/máx/centro, `center_metrics` (perda combinada, ganho efetivo, campo central, trajetória, distância) e `images` para ambas unidades (`dbuv`, `dbm`) com suas respectivas escalas.
  - O endpoint também sinaliza `location_status` comparando a posição atual com a última coleta climática e inclui `signal_level_dict_dbm` para interpolar níveis em dBm nos marcadores RX.
- **Perfil profissional (`/gerar_img_perfil`)**:
  - Reutiliza padrões horizontal/vertical e tilt para gerar gráfico emissivo: terreno sombreado, curvatura, 1ª zona de Fresnel, linha direta e anotação (ERP, ΔG, campo RX, perdas ITU). Inclui mini gráfico do padrão horizontal em dB.
- **Dados do usuário**: rotas para salvar/carregar parâmetros (`/salvar-dados`, `/carregar-dados`), atualizar tilt (`/update-tilt`), obter diagramas (`/carregar_imgs`) e gerar relatórios (`/gerar-relatorio`).
- **Helpers compartilhados**: conversão de dB⇄campo, autoescala, máscara circular, cálculos de Fresnel, ajustes de centro, etc.

## Frontend

### Layout e assets
- `templates/layouts/base.html` define cabeçalho, navegação, toasts e slots para CSS/JS.
- CSS global em `static/css/main.css` e específicos em `static/css/pages/*.css`.
- JS modular em `static/js/main.js` e `static/js/pages/*.js` (ES6, estado encapsulado, fallback para compatibilidade onde necessário).

### Páginas remodeladas
- **Landing/Login/Registro/Home**: converteram para o novo layout com validação moderna.
- **Antena** (`templates/antena.html`, `static/js/pages/antenna.js`): sidebar fixa, upload `.pat`, sliders de direção/tilt, preview em tempo real e funções globais expostas (`salvarDiagrama`, `sendDirectionAndFile`, `applyTilt`).
- **Calcular Cobertura** (`templates/calcular_cobertura.html`, `static/js/pages/cobertura.js`): formulário segmentado, campo de tilt, modais compatíveis com/sem Bootstrap e integração com `/calculate-coverage`.
- **Mapa Profissional** (`templates/mapa.html`, `static/css/pages/map.css`, `static/js/pages/mapa.js`):
  - Painel lateral com cartões (dados da TX, sliders, lista de RX, resumo de ganhos, ligação TX↔RX, colorbar).
  - Mapa Google com marcador TX arrastável, múltiplos pontos RX (lista interativa com foco/remover), polilinha TX↔RX, círculo do raio e overlay de cobertura com transparência ajustável.
  - Slider de opacidade, feedback visual, modal com perfil profissional.
  - Novo card de perdas P.452, painel de indicadores centrais, rótulo profissional para a colorbar e botões para alternar entre dBµV/m e dBm (com disponibilidade automática conforme o backend retornar ou não a camada dBm).
  - Spinner “Gerando cobertura...” sobre o mapa e mensagens de status no topo dos cartões quando há mudança de localização/tilt sem nova mancha.

## Fluxos

1. **Cobertura**
   - Formulário salva parâmetros em `/salvar-dados`.
   - `/calculate-coverage` recebe raio, limites, centro customizado e agora também aplica `timePercentage`, polarização, versão da Recomendação ITU-R P.452, temperatura, pressão e densidade de vapor configuradas na página ⇒ pycraf ⇒ campo elétrico (`dBµV/m`) com máscara circular ⇒ resposta JSON (imagem, colorbar, `gain_components`, escala, centro, raio). O frontend desenha overlay, círculo e atualiza resumos.
   - Endpoint `/clima-recomendado` consulta a Open-Meteo (médias horárias dos últimos 360 dias) para sugerir temperatura média, pressão e densidade de vapor, populando automaticamente a ficha de condições atmosféricas.
   - A camada agora devolve `loss_components`, `center_metrics`, `signal_level_dict_dbm`, `location_status` e o par de imagens (`dbuv`, `dbm`). O front-end alterna entre unidades, recalcula listas RX, atualiza o card de perdas/indicadores e exibe o spinner durante o processamento.
2. **Controle TX/RX**
   - TX arrastável atualiza painel e sugere recalcular cobertura; posição é salva ao chamar `/calculate-coverage`.
   - Cada clique adiciona RX à lista; distância, campo estimado (via dicionário retornado) e elevação (Google Elevation) são calculados. A lista permite focar, remover e gerar perfil.
3. **Perfil profissional**
   - `/gerar_img_perfil` gera gráfico com terreno sombreado, curvatura, Fresnel, linha direta, anotação e mini padrão horizontal. Resultado exibido no modal e armazenado no banco.

## Alterações Recentes
- Modularização do backend (`app_core`), uso de factory e serviço systemd ajustado.
- Conversão de todas as páginas para o layout base com assets organizados.
- Cobertura calculada em `dBµV/m` respeitando ganhos horizontal e vertical provenientes do arquivo `.pat` (incluindo tilt e direção).
- Nova experiência `/mapa`: painel profissional, TX arrastável, múltiplos RX, slider de opacidade, círculo de raio e overlay com transparência ajustável.
- Perfil do enlace redesenhado (terreno sombreado, Fresnel destacado, mini diagrama horizontal em dB e anotação rica).
- Conversão potência→campo corrigida para `E = P_rx + 77,2 + 20*log10(f_MHz)` (descontando `G_rx`), evitando a superestimação anterior (~70 dBµV/m para −65 dBm @100 MHz).
- Resolução do grid SRTM agora depende do raio (640/512/384 px) para manter o uso de RAM previsível; o front-end apenas sinaliza com spinner sem travar a interação com o mapa.
- Perfil profissional com escala vertical reancorada (30% abaixo do ponto mais baixo), torres proporcionais e quadro de resumo reposicionado na base.
- Ganhos horizontal/vertical tratados integralmente em dB: o delta de diagrama é normalizado (0 dB no boresight), o tilting elétrico é aplicado via `E/Emax` em 0° e a componente vertical em cada ponto considera o desvio `α + tilt`.
- Perfil profissional destaca obstruções da 1ª Fresnel diretamente no traçado e apresenta um painel inferior com métricas do enlace.
- Tela de planejamento (`/calcular-cobertura`) inclui campos profissionais para percentual de tempo (p%), polarização, versão da ITU-R P.452, temperatura, pressão e densidade de vapor d'água, persistidos no banco e aplicados nos cálculos do pycraf.
- A localização da TX grava município e altitude (SRTM) automaticamente; clima histórico (últimos 12 meses) é consultado via Open-Meteo e o backend alerta quando a posição muda sem novo ajuste climático.
- Resposta de cobertura expandida com `loss_components`, `center_metrics`, `signal_level_dict_dbm`, dupla escala (dBµV/m ↔ dBm) e status de localização/clima; o front-end ganhou cartão de perdas, indicadores centrais, rótulo de colorbar, spinner dedicado e botões de unidade.

## Próximos Passos
1. **Geração da Mancha**
   - Validar os ajustes de ganho e a nova conversão para campo frente a medições reais (incluindo cenários com diferentes ganhos RX).
   - Investigar interpolação bilinear para `signal_level_dict`, evitando degraus perceptíveis ao consultar valores próximos ao pixel original.
2. **Exportação KML/KMZ**
   - Implementar endpoint para exportar a mancha (polígonos graduais ou raster KMZ) e disponibilizar download.
3. **Performance**
   - Cachear resultados SRTM/pycraf (disco ou Redis) e considerar uso de fila assíncrona (RQ/Celery).
4. **Antena**
   - Expor métricas avançadas (HPBW, diretividade) e histórico de uploads, além de ajustes finos (normalização manual, espelhamento).

Este documento resume a arquitetura, as melhorias implantadas e o roteiro imediato para corrigir e evoluir a geração de cobertura georreferenciada.
