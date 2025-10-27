ma Análise Técnica Abrangente da Biblioteca pycraf para Propagação de RF e Gestão de Espectro

Seção 1: Introdução e Contexto Científico

Esta seção estabelece o problema fundamental que a pycraf foi criada para resolver. Ela enquadra a biblioteca não apenas como um software, mas como uma ferramenta crítica no esforço científico e regulatório contínuo para proteger serviços de rádio sensíveis de um espectro eletromagnético cada vez mais congestionado.

1.1 O Desafio Crítico da Gestão de Espectro

O espectro de radiofrequências é um recurso finito e compartilhado, essencial para as comunicações modernas, navegação e empreendimentos científicos. O uso não coordenado deste recurso leva inevitavelmente à Interferência de Radiofrequência (RFI), que pode degradar ou até mesmo desativar serviços críticos. Esta realidade impõe a necessidade de um processo formal de "gestão de espectro" para garantir a compatibilidade entre diferentes serviços de rádio. A gestão de espectro é um esforço global, amplamente coordenado pela União Internacional de Telecomunicações (UIT), um órgão especializado das Nações Unidas. A UIT desenvolve Recomendações (padrões técnicos) que fornecem metodologias para calcular a interferência e garantir a coexistência harmoniosa. A biblioteca pycraf é uma ferramenta de software projetada especificamente para implementar esses padrões complexos em um ambiente de programação moderno, tornando os cálculos de compatibilidade acessíveis, repetíveis e transparentes.  

1.2 A Vulnerabilidade Única do Serviço de Radioastronomia (RAS)

Dentro do ecossistema de serviços de rádio, o Serviço de Radioastronomia (RAS) ocupa uma posição de extrema vulnerabilidade. Os observatórios de radioastronomia utilizam receptores de sensibilidade extraordinária para detectar sinais cósmicos incrivelmente fracos, tornando-os "dezenas de ordens de magnitude" mais sensíveis do que os serviços de comunicação comerciais. A RFI de origem humana, mesmo de transmissores de baixa potência a grandes distâncias, pode facilmente sobrecarregar esses sinais astronômicos. Tal interferência pode levar à perda parcial ou total de dados observacionais ou, em casos extremos, até mesmo danificar os componentes eletrônicos sensíveis, tornando os radiotelescópios efetivamente "cegos".  

A proteção do RAS é, portanto, uma das principais motivações por trás do desenvolvimento de ferramentas de análise de espectro como a pycraf. Um caso de uso paradigmático, frequentemente citado na documentação da biblioteca, é o cálculo dos níveis de interferência em um radiotelescópio causados por uma torre de transmissão de rádio ou televisão próxima. A sensibilidade extrema do RAS o torna a "vítima" de pior caso em muitos estudos de compatibilidade. Consequentemente, uma ferramenta que pode modelar com precisão a interferência para a radioastronomia é inerentemente robusta o suficiente para analisar cenários envolvendo quase qualquer outro serviço de rádio.  

1.3 Gênese e Curadoria da pycraf

A biblioteca pycraf foi desenvolvida pelo Comitê de Especialistas em Frequências de Radioastronomia (CRAF), um órgão da Fundação Europeia da Ciência (ESF), para auxiliar na condução de estudos de compatibilidade de espectro. Os autores principais da biblioteca são Benjamin Winkel, Marta Bautista, Federico Di Vruno e Gyula I. G. Józsa, especialistas que trabalham diretamente na interface entre a radioastronomia e a gestão de espectro. O projeto é mantido ativamente, com seu código-fonte hospedado publicamente no GitHub e os lançamentos de pacotes registrados no Python Package Index (PyPI), garantindo fácil acesso à comunidade global. A origem da biblioteca dentro de um comitê científico respeitado como o CRAF confere-lhe uma credibilidade significativa. Ela nasceu de uma necessidade direta de especialistas da área que consideraram as ferramentas existentes inadequadas para seus requisitos específicos, baseados em padrões e cientificamente rigorosos.  

1.4 Filosofia Central: Uma Ferramenta de Código Aberto Baseada em Padrões

A filosofia fundamental da pycraf é fornecer uma implementação nativa em Python e de código aberto (licenciada sob a GPL v3) das principais Recomendações da UIT-R. Isso a diferencia de ferramentas proprietárias ou de soluções que são difíceis de integrar em fluxos de trabalho de análise automatizados. O objetivo principal é simplificar, padronizar e tornar transparente o aspecto técnico dos estudos de compatibilidade, que são cruciais para as negociações de espectro.  

Essa abordagem posiciona a pycraf não apenas como uma calculadora, mas como uma ferramenta de "diplomacia científica". Disputas de espectro surgem de usos conflitantes de um recurso compartilhado. A resolução dessas disputas requer uma estrutura técnica comum para prever e quantificar a interferência. A UIT fornece essa estrutura por meio de suas Recomendações. No entanto, as implementações desses algoritmos complexos podem variar, levando a resultados diferentes e desconfiança entre as partes interessadas. Softwares proprietários de "caixa-preta" exacerbam esse problema. Ao fornecer uma implementação de código aberto dos padrões da UIT, a pycraf permite que todas as partes (por exemplo, astrônomos, reguladores e empresas de telecomunicações) inspecionem o código, verifiquem os algoritmos e cheguem a um acordo sobre a validade dos resultados. Isso desloca o debate de "qual software está certo?" para "quais são os parâmetros de entrada corretos?", um problema muito mais tratável. Portanto, a pycraf não é apenas um motor de cálculo; é uma ferramenta para construir consenso técnico.

Seção 2: Visão Geral da Arquitetura e Fundamentos Técnicos

Esta seção detalha os princípios de engenharia de software por trás da pycraf, enfatizando como suas escolhas de design permitem uma computação científica robusta, precisa e eficiente.

2.1 Integração Profunda com o Ecossistema Científico Python

A pycraf não é uma aplicação isolada, mas sim uma biblioteca projetada para funcionar dentro do ecossistema de análise de dados científicos mais amplo do Python. Ela é construída sobre uma base de bibliotecas científicas centrais, incluindo NumPy para computação numérica, SciPy para algoritmos científicos e, mais importante, Astropy para funcionalidades específicas da astronomia. A estrutura do pacote utiliza o Astropy Package Template, um padrão comunitário que garante consistência e interoperabilidade. Essa integração permite que os resultados da pycraf sejam passados de forma transparente para outras ferramentas para visualização (com matplotlib), análise estatística ou incorporação em estruturas de simulação maiores.  

2.2 O Papel das Unidades e Quantidades Astropy para a Correção Física

Uma das características de design mais críticas da pycraf é o uso extensivo do pacote astropy.units. Todas as entradas e saídas de funções são objetos Quantity, que associam um valor numérico à sua unidade física correspondente (por exemplo, 10 MHz, 50 km). Esta não é uma mera conveniência, mas um mecanismo fundamental para garantir a correção física e prevenir erros comuns na computação científica, como incompatibilidades de unidades (por exemplo, confundir metros com quilômetros ou dBW com dBm). A biblioteca lida automaticamente com as conversões de unidades, garantindo que as equações físicas subjacentes sejam sempre avaliadas com entradas dimensionalmente consistentes.  

O uso obrigatório de astropy.units eleva a pycraf de uma simples biblioteca numérica para um kit de ferramentas "fisicamente ciente". Os cálculos de propagação de RF envolvem dezenas de grandezas físicas com unidades diferentes. Uma biblioteca tradicional exigiria que o usuário garantisse manualmente que todas as entradas estivessem nas unidades esperadas, um processo altamente propenso a erros. Ao usar astropy.units, a pycraf delega o gerenciamento de unidades para a estrutura. Um usuário pode fornecer uma distância como 10 * u.km ou 10000 * u.m, e a lógica interna da biblioteca irá tratá-la corretamente. Essa escolha de design aumenta significativamente a confiabilidade e a reprodutibilidade dos cálculos, forçando o usuário a ser explícito sobre a natureza física de seus dados.

2.3 Otimização de Desempenho através do Cython

Os cálculos de propagação, especialmente sobre grandes áreas ou múltiplas frequências, podem ser computacionalmente intensivos. O Python puro, sendo uma linguagem interpretada, pode ser muito lento para essas tarefas. Para superar essa limitação, a pycraf tem uma dependência estrita do Cython. Partes computacionalmente críticas do código, como os modelos atmosféricos detalhados, são implementadas em Cython. O Cython permite que os desenvolvedores escrevam código semelhante ao Python que é transpilado para C e compilado, proporcionando ganhos de desempenho significativos para laços numéricos e operações críticas. Os classificadores do pacote no PyPI também listam C e Cython como linguagens de implementação, refletindo essa abordagem de otimização.  

2.4 Design Modular: Estrutura de Subpacotes

Seguindo as melhores práticas de design de software, a pycraf é organizada em subpacotes lógicos que separam diferentes áreas de funcionalidade. A estrutura inclui módulos como pathprof (para propagação de percurso), atm (para efeitos atmosféricos), conversions (para conversão de unidades e grandezas), antenna (para padrões de antena) e protection (para critérios de proteção regulatórios). A documentação oficial é estruturada em torno desses módulos, facilitando a navegação e o aprendizado. Essa modularidade torna a biblioteca mais fácil de entender, manter e estender. Um usuário interessado apenas em atenuação atmosférica pode importar e aprender o subpacote atm sem precisar entender as complexidades da difração de terreno no pathprof.  

Seção 3: Instalação e Configuração do Ambiente

Esta seção fornece um guia prático e passo a passo para instalar a pycraf e, crucialmente, suas dependências de dados externos. Ela destaca possíveis armadilhas e as melhores práticas para uma configuração bem-sucedida.

3.1 Requisitos de Sistema e Dependências

A pycraf exige uma versão moderna do Python (3.8+ ou 3.10+, dependendo da versão da biblioteca). Além do interpretador Python, ela depende de um conjunto específico de bibliotecas científicas, incluindo numpy, scipy, astropy, cython e pyproj. Devido ao uso do Cython para otimização de desempenho, a instalação a partir de algumas fontes (como o pip) pode exigir um compilador C com suporte a OpenMP no sistema do usuário. Este requisito de compilador pode ser um obstáculo para usuários não acostumados com código compilado, especialmente em ambientes Windows e macOS.  

3.2 Instalação Recomendada: Anaconda e conda-forge

Os desenvolvedores da pycraf "recomendam fortemente" o uso da distribuição Python Anaconda. O Anaconda simplifica o gerenciamento de dependências complexas, especialmente aquelas com componentes compilados em C/Fortran. A instalação é realizada através do canal conda-forge, um repositório mantido pela comunidade que fornece pacotes binários pré-compilados para todos os principais sistemas operacionais. Isso contorna a necessidade de os usuários terem um compilador local configurado.  

O comando de instalação é: conda install -c conda-forge pycraf  

É considerada uma boa prática instalar a pycraf e suas dependências em um ambiente virtual conda dedicado para evitar conflitos com outros projetos. Isso pode ser feito com um comando como: conda create -n pycraf-env -c conda-forge python=3.10 pycraf  

3.3 Instalação Alternativa: pip e a partir do Código-Fonte

Para usuários que não podem ou não desejam usar o Anaconda, a instalação via pip é uma alternativa: pip install pycraf  

No entanto, como mencionado, este método pode falhar se um compilador C compatível não estiver presente. A documentação fornece orientações específicas para superar isso em diferentes sistemas operacionais, como a instalação das Ferramentas de Compilação do Visual Studio no Windows ou de um compilador compatível com OpenMP (como o LLVM) no macOS.  

Usuários avançados também podem instalar a biblioteca diretamente do código-fonte, clonando o repositório do GitHub e executando o script de instalação.  

3.4 Passo Crítico: Configuração de Fontes de Dados Externas

A funcionalidade completa da pycraf depende de conjuntos de dados externos que devem ser configurados pelo usuário. A instalação do pacote Python por si só não é suficiente.

    Dados de Terreno SRTM: Para os cálculos de perfil de percurso no módulo pathprof (implementando a UIT-R P.452), são necessários dados da Missão Topográfica por Radar do Ônibus Espacial (SRTM) da NASA. A pycraf trabalha com os arquivos de formato .hgt. O usuário é responsável por baixar esses arquivos (disponíveis publicamente) e informar à biblioteca sua localização no sistema de arquivos. Isso é feito definindo a variável de ambiente SRTMDATA para apontar para o diretório que contém os arquivos .hgt. Por exemplo, em um sistema Linux ou macOS: export SRTMDATA=/caminho/para/dados/srtm/.   

Dados da UIT: A pycraf convenientemente agrupa os arquivos de dados necessários da UIT para os modelos atmosféricos (P.676) e dados radiometeorológicos (P.452). A UIT concedeu permissão para esta distribuição, o que simplifica muito a configuração do usuário. No entanto, é crucial notar que esses dados não são livres para uso comercial. Os detalhes da licença estão contidos em um arquivo LICENSE.ITU dentro do pacote.  

Essa dependência de dados externos e seu licenciamento específico criam um modelo de confiabilidade de duas vias para a biblioteca. O código em si é de código aberto, mas para produzir resultados cientificamente válidos para suas funções principais, ele requer esses conjuntos de dados. A capacidade de um usuário usar a pycraf de forma legal e eficaz depende, portanto, de seu caso de uso (comercial vs. não comercial) e de sua diligência na configuração correta das variáveis de ambiente. Uma instalação "padrão" sem definir SRTMDATA terá funcionalidade severamente limitada no módulo pathprof.

3.5 Verificando a Instalação

Após a instalação e configuração, os usuários podem e devem executar um conjunto de testes abrangente incluído na biblioteca. Isso é feito executando os seguintes comandos em um interpretador Python: import pycraf pycraf.test()  

Por padrão, os testes que requerem acesso à internet (por exemplo, para baixar alguns blocos de teste de dados SRTM) são ignorados. Eles podem ser ativados com o argumento remote_data: pycraf.test(remote_data='any')  

A presença de um conjunto de testes integrado e executável pelo usuário é uma marca de um pacote de software científico maduro e bem mantido. Ele permite que os usuários confirmem que a biblioteca e suas dependências estão funcionando corretamente em seu ambiente específico.

Seção 4: O Módulo pathprof: Análise de Propagação Terrestre

Esta seção constitui o núcleo do relatório, fornecendo um mergulho profundo na característica mais significativa da pycraf: a implementação da Recomendação UIT-R P.452.

4.1 O Padrão UIT-R P.452: Uma Visão Geral Detalhada

O subpacote pathprof é descrito como "provavelmente a parte mais importante da pycraf". Ele fornece uma "implementação completa da Rec. UIT-R P.452-17". Esta recomendação detalha um procedimento abrangente para prever a perda de propagação em percursos terrestres para frequências na faixa de aproximadamente 0.7 a 50 GHz. A metodologia da P.452 é o padrão internacional para este tipo de análise e combina vários efeitos físicos distintos para chegar a uma perda de percurso total, considerando a estatística temporal (ou seja, a perda não excedida por uma certa porcentagem do tempo).  

4.2 Gerando Perfis de Percurso a partir de Dados de Terreno

O primeiro passo em qualquer cálculo P.452 é determinar o perfil do terreno entre o transmissor (Tx) e o receptor (Rx). A função pathprof.height_path_data é usada para essa finalidade. Ela recebe as coordenadas de longitude e latitude dos pontos finais e um tamanho de passo como entrada. Internamente, ela consulta os dados SRTM (configurados através da variável de ambiente SRTMDATA) para extrair as elevações ao longo do grande círculo que conecta os dois pontos. O resultado é um dicionário contendo arrays de distâncias e as alturas correspondentes do terreno, além de outros dados auxiliares necessários para os cálculos subsequentes.  

Um exemplo de uso típico seria:
Python

import astropy.units as u
from pycraf import pathprof

# Coordenadas do Transmissor e Receptor
lon_t, lat_t = 6.8836 * u.deg, 50.525 * u.deg
lon_r, lat_r = 7.3334 * u.deg, 50.635 * u.deg
hprof_step = 100 * u.m

# Gerar dados do perfil de altura
hprof_data = pathprof.height_path_data(
    lon_t, lat_t, lon_r, lat_r, hprof_step
)

# hprof_data['distances'] e hprof_data['heights'] podem agora ser usados para plotagem ou análise

4.3 Função Principal: atten_path_fast

Esta é a função central para o cálculo da atenuação do percurso. Ela é projetada para ser eficiente e aceita numerosos parâmetros que definem a geometria do percurso, as condições atmosféricas e as características do local. Os principais parâmetros incluem frequência, temperatura, pressão, os dados do perfil de altura (hprof_data), as alturas das antenas acima do solo (h_tg, h_rg), a porcentagem de tempo para a qual a perda é calculada e as zonas de "clutter" (desordem/obstáculos locais) para o transmissor e o receptor.  

A função retorna um dicionário abrangente contendo as perdas calculadas para vários mecanismos de propagação e a perda total combinada. As chaves de retorno incluem L_b (perda de propagação total), L_bd (perda básica de transmissão incluindo difração), L_bs (perda por dispersão troposférica), L_ba (perda por dutos/reflexão em camada) e path_type (indicando se o percurso é de linha de visada ou trans-horizonte).  

4.4 Desconstrução dos Componentes da Perda de Percurso (O Método P.452)

A perda total do percurso, conforme calculada pela P.452, é uma combinação complexa de vários efeitos físicos. A pycraf implementa cada um desses componentes, que são então combinados para fornecer o resultado final.  

    Linha de Visada (LoS) e Perda no Espaço Livre: Este é o componente mais básico da perda de propagação, que inclui a perda geométrica no espaço livre e a atenuação devido a gases atmosféricos. É calculado pela função loss_freespace.

    Perda por Difração: Esta é a perda causada por obstruções do terreno (como montanhas ou a curvatura da Terra) que bloqueiam o percurso direto. É um dos cálculos mais complexos na P.452. É importante notar que a pycraf implementa o método mais recente de Bullington com correções, que substituiu o método de Deygout na versão 15 da P.452. Isso demonstra o compromisso da biblioteca em se manter atualizada com a evolução dos padrões. A função correspondente é loss_diffraction.   

Perda por Dispersão Troposférica: Para longos percursos sobre o horizonte, a dispersão de ondas de rádio pela turbulência na troposfera se torna um mecanismo de propagação dominante. Este efeito é calculado pela função loss_troposcatter.

Dutos e Propagação Anômala: Sob certas condições atmosféricas, podem se formar camadas (dutos) que aprisionam e guiam as ondas de rádio, permitindo que elas viajem muito além do horizonte com atenuação anormalmente baixa. Este mecanismo é calculado pela loss_ducting.

Perda por "Clutter": Este termo refere-se à atenuação adicional causada por obstáculos próximos às antenas, como edifícios e vegetação, que não são resolvidos pelos dados de terreno SRTM. A pycraf permite que o usuário especifique o tipo de ambiente local (por exemplo, pathprof.CLUTTER.URBAN, pathprof.CLUTTER.SUBURBAN) e aplica uma correção de clutter apropriada usando a função clutter_correction.  

4.5 Funcionalidades Avançadas do pathprof

Além do cálculo de percurso ponto a ponto, o módulo pathprof oferece funcionalidades mais avançadas:

    Mapas de Atenuação: A pycraf pode calcular a atenuação sobre uma grade 2D usando as funções atten_map_fast e height_map_data. Isso é extremamente útil para visualização de cobertura, planejamento de rede e determinação de zonas de exclusão em torno de locais sensíveis.   

### Componentes devolvidos por `atten_map_fast`

Ao gerar o mapa com `pycraf.pathprof.atten_map_fast`, o retorno é um dicionário com diversas componentes de perda que ajudam a qualificar o trajeto calculado pela recomendação UIT-R P.452:

- **`L_b0p`** – perda básica por difração (modo sub-refrativo) sem considerar ducting.
- **`L_bd`** – difração por obstáculos/relévo dominante ao longo do percurso.
- **`L_bs`** – espalhamento troposférico dominante.
- **`L_ba`** – atenuação adicional por absorção gasosa na baixa atmosfera.
- **`L_b`** – perda total combinada (dB) antes de aplicar correções específicas do cenário.
- **`L_b_corr`** – perda ajustada considerando interpolação de modo ducting/sub-refrativo (quando aplicável). Quando disponível, esse valor deve ser usado como perda total do enlace.
- **`path_type`** – matriz categórica indicando o mecanismo dominante em cada ponto da grade (`LOS`, `NLOS`, `DIFFRACTION`, `TROPOSCATTER`, etc.).

No ATX Coverage, essas matrizes são convertidas para dB (via `.to(u.dB).value`) e resumidas em três métricas (mínimo, máximo e valor no pixel central) para alimentar o painel de perdas na interface. Quando `L_b_corr` está ausente, o sistema faz o fallback para `L_b`, garantindo um valor único de perda combinada que é usado tanto no link budget quanto na geração das camadas dBµV/m/dBm.

Geodésia: Para cálculos precisos de distância e azimute sobre a superfície da Terra, é essencial levar em conta a forma elipsoidal do planeta. A biblioteca inclui funções para resolver problemas geodésicos diretos (dada uma posição inicial, azimute e distância, encontrar a posição final) e inversos (dadas duas posições, encontrar a distância e os azimutes) usando as fórmulas de Vincenty, que são altamente precisas. As funções são geoid_direct e geoid_inverse.  

Seção 5: O Módulo atm: Efeitos Atmosféricos e Percursos Inclinados

Esta seção aborda o segundo grande padrão da UIT implementado na pycraf, focando na atenuação por gases atmosféricos e vapor d'água, que é crítica para comunicações por satélite, astronomia de ondas milimétricas e enlaces terrestres de alta frequência.

5.1 O Padrão UIT-R P.676: Atenuação Gasosa

O subpacote atm fornece uma "implementação completa da Rec. UIT-R P.676-13". Este padrão descreve um modelo físico para calcular a atenuação causada pelas linhas de absorção espectral do oxigênio e do vapor d'água na atmosfera terrestre. O modelo é válido para frequências de 1 a 1000 GHz.  

5.2 Modelos do Anexo 1 vs. Anexo 2

A Recomendação P.676 oferece dois modelos distintos:

    Modelo do Anexo 1: Este é o modelo mais preciso e fisicamente rigoroso. Ele constrói o espectro de atenuação a partir da soma das contribuições de dezenas de linhas de ressonância individuais de oxigênio e vapor d'água, além de um contínuo de absorção. É válido em toda a faixa de 1 a 1000 GHz.

    Modelo do Anexo 2: Este é um modelo empírico mais simples e rápido, válido apenas até 350 GHz. Ele não calcula a atenuação camada por camada, mas usa uma abordagem de "altura equivalente" para estimar a perda total.

A pycraf implementa ambos os modelos. No entanto, a documentação orienta os usuários a preferirem o modelo do Anexo 1. Embora o modelo do Anexo 2 seja conceitualmente mais simples, a implementação do Anexo 1 na pycraf foi altamente otimizada com Cython, tornando-a "razoavelmente rápida". Essa recomendação reflete uma filosofia que prioriza a precisão e a fidelidade física. A biblioteca orienta ativamente os usuários para o método mais robusto, minimizando a penalidade de desempenho por meio de uma implementação eficiente.  

5.3 Definindo Perfis Atmosféricos

Para calcular a atenuação através da atmosfera, é necessário um perfil de temperatura, pressão e umidade em função da altitude. O módulo pycraf.atm fornece vários perfis padrão baseados na Recomendação UIT-R P.835-5, que são representativos de diferentes condições geográficas e sazonais, como profile_standard, profile_midlat_summer, profile_highlat_winter, etc.. Uma característica importante é a flexibilidade para que os usuários forneçam seus próprios perfis atmosféricos personalizados. Isso é crucial para estudos de alta precisão em locais específicos, como observatórios de radioastronomia situados em locais de alta altitude e baixa umidade, onde os perfis padrão não seriam representativos.  

5.4 Calculando a Atenuação

O processo de cálculo da atenuação atmosférica envolve duas etapas principais:

    Atenuação Específica: A função atten_specific_annex1 calcula a perda em dB/km para uma determinada frequência, pressão, temperatura e teor de vapor d'água. Este valor representa a atenuação em uma pequena porção (laje) da atmosfera.   

Atenuação Total (Percurso Inclinado): Para um sinal que atravessa toda a atmosfera (por exemplo, de um satélite para uma estação terrestre), a função atten_slant_annex1 calcula a perda de percurso total. Ela realiza isso dividindo a atmosfera em centenas de camadas discretas, calculando a atenuação específica em cada camada usando o perfil atmosférico e, em seguida, integrando a perda ao longo do percurso do sinal. Este processo também inclui o traçado de raios (ray-tracing) para levar em conta a refração atmosférica, que curva o caminho do sinal.  

Um exemplo de código para um percurso terrestre simples seria:
Python

import astropy.units as u
from pycraf import atm

freqs =  * u.GHz
total_pressure = 1013 * u.hPa
temperature = 290 * u.K
humidity = 50 * u.percent
path_length = 10 * u.km

# Calcula a pressão parcial da água a partir da umidade relativa
pressure_water = atm.pressure_water_from_humidity(
    temperature, total_pressure, humidity
)
# Calcula a pressão do ar seco
pressure_dry = total_pressure - pressure_water

# Calcula a atenuação específica (dB/km)
specific_atten = atm.atten_specific_annex1(
    freqs, pressure_dry, pressure_water, temperature
)

# Calcula a atenuação total ao longo do percurso
total_atten = atm.atten_terrestrial(specific_atten, path_length)

Seção 6: Uma Análise Detalhada dos Módulos de Suporte

Esta seção detalha os módulos utilitários que apoiam os cálculos de propagação principais, tornando a pycraf um kit de ferramentas abrangente para estudos de compatibilidade.

6.1 pycraf.conversions

Este módulo é fundamental para o trabalho prático em engenharia de RF, fornecendo um conjunto de funções para converter entre as diversas grandezas físicas utilizadas na área. Isso inclui densidade de fluxo de potência, intensidade de campo elétrico, potência transmitida (Ptx), potência recebida (Prx), ganho de antena e área efetiva.  

Uma característica chave é a definição de unidades astropy personalizadas para variantes comuns de decibéis. Isso inclui dBm (dB relativo a 1 mW), dBi (dB relativo a uma antena isotrópica) e a unidade especializada dB_uV_m (dB relativo a 1 µV²/m²), que é comumente usada em regulamentação de emissões. A integração com o sistema de unidades astropy permite que cálculos envolvendo essas unidades logarítmicas sejam realizados de forma transparente e fisicamente correta.  

A tabela a seguir resume algumas das funções mais importantes neste módulo:
Função	Finalidade
free_space_loss(dist, freq)	Calcula a perda de propagação no espaço livre.
powerflux_from_ptx(ptx, dist, gtx)	Calcula a densidade de fluxo de potência a uma certa distância de um transmissor.
efield_from_powerflux(powerflux)	Converte densidade de fluxo de potência em intensidade de campo elétrico.
prx_from_powerflux(powerflux, freq, grx)	Calcula a potência recebida por uma antena a partir de uma densidade de fluxo de potência.
prx_from_ptx(ptx, gtx, grx, dist, freq)	Calcula a potência recebida usando a equação de transmissão de Friis.
gain_from_eff_area(eff_area, freq)	Converte a área efetiva da antena em ganho.
eff_area_from_gain(gain, freq)	Converte o ganho da antena em área efetiva.

6.2 pycraf.antenna

Este módulo fornece implementações de modelos padrão de padrões de radiação de antena, que são um ingrediente essencial para qualquer estudo de compatibilidade. Em vez de exigir que os usuários implementem esses modelos complexos a partir de documentos de padrões, a pycraf os fornece prontos para uso. Os padrões implementados incluem:  

    Telescópios de Radioastronomia: Um padrão de ganho genérico para radiotelescópios de prato único, conforme definido na Recomendação UIT-R RA.1631-0.   

Antenas IMT-2020 (5G): Padrões para antenas de arranjo de fase (phased array) usadas em estações base e dispositivos móveis 5G. Estes são cruciais para estudos de compatibilidade com as novas redes de telefonia celular.  

Enlaces de Serviço Fixo: Padrões para as antenas altamente direcionais usadas em enlaces de micro-ondas ponto a ponto, conforme a Recomendação UIT-R F.699-7.  

6.3 pycraf.protection

Este é um módulo de conveniência que encapsula vários limiares de proteção regulatória e limites de emissão, evitando que os usuários tenham que procurar esses valores em documentos de padrões. Ele fornece acesso programático a esses números críticos. Os critérios implementados incluem:  

    Limites de Proteção do RAS: Os limiares de interferência prejudicial para o Serviço de Radioastronomia, conforme detalhado nas Tabelas 1 e 2 da Recomendação UIT-R RA.769. Isso inclui limites para observações de contínuo e de linha espectral, que podem ser ajustados para diferentes tempos de integração.   

Limites de Emissão CISPR: Limites de emissão para equipamentos Industriais, Científicos e Médicos (ISM), conforme os padrões CISPR-11 e CISPR-22, que são importantes para avaliar a interferência de equipamentos não intencionalmente radiantes.  

Um exemplo de como obter os limites do RAS:
Python

from pycraf import protection
import astropy.units as u

# Obter a tabela de limites para observações de contínuo
# com um tempo de integração de 2000 segundos (padrão)
limites_ras = protection.ra769_limits(mode='continuum')

# Acessar o limite de densidade de fluxo de potência espectral para uma banda específica
limite_banda_2_ghz = limites_ras

Seção 7: Aplicações Práticas e Estudos de Caso

Esta seção passa da teoria para a prática, mostrando como a pycraf é usada para resolver problemas do mundo real em gestão de espectro e radioastronomia.

7.1 Estudo de Caso: Análise de Blindagem de RFI para o Telescópio SKA

A pycraf desempenhou um papel importante no projeto do Square Kilometre Array (SKA), o maior radiotelescópio do mundo. Foi utilizada para modelar e controlar a RFI gerada internamente dentro do próprio observatório. Um estudo específico usou a pycraf para gerar um mapa de atenuação a 2.8 GHz a partir do edifício de processamento central, onde os computadores e a eletrônica geram ruído de rádio, para cada uma das antenas do telescópio. A estrutura de simulação de RFI para o SKA-Low usa explicitamente a pycraf para seus cálculos de propagação.  

Este estudo de caso ilustra um fluxo de trabalho típico:

    Definir o Transmissor: O edifício de processamento central é modelado como uma fonte de RFI com uma determinada localização e potência de emissão.

    Definir os Receptores: As localizações de cada antena do SKA são definidas como os pontos receptores.

    Calcular a Perda de Percurso: Usando a pycraf, a perda de propagação do edifício para cada antena é calculada, levando em conta o terreno local.

    Analisar a Margem de Interferência: O nível de interferência resultante em cada antena é comparado com o limiar de sensibilidade do telescópio para determinar a "margem" de segurança. Isso permite que os engenheiros projetem blindagem de RFI adequada para o edifício, garantindo que ele não contamine suas próprias observações.

7.2 Estudo de Caso: Simulação do Impacto de Redes 5G em um Observatório de Rádio

Um artigo de pesquisa fundamental destaca o uso da pycraf para analisar o dano potencial das redes de telefonia celular de 5ª geração (5G) às observações em um observatório de rádio. A natureza das redes 5G, com um grande número de estações base e dispositivos de usuário distribuídos de forma quase estatística, torna uma análise simples ponto a ponto inadequada.  

Para resolver isso, os pesquisadores implementaram uma simulação de Monte Carlo. Este estudo de caso demonstra o poder da natureza programável da pycraf:  

    Motor de Cálculo Central: A pycraf atua como o motor de cálculo de propagação dentro de um laço estatístico maior.

    Simulação Estatística: O laço gera aleatoriamente milhares de localizações potenciais para estações base e dispositivos de usuário 5G em uma área ao redor do observatório, com base em modelos de implantação realistas.

    Cálculo Agregado: Para cada iteração, a pycraf calcula a perda de percurso de cada interferente simulado para o radiotelescópio.

    Análise de Resultados: As contribuições de interferência de todos os emissores são somadas para calcular o nível de interferência "agregado". A simulação é executada milhares de vezes para construir uma distribuição estatística do nível de interferência esperado, permitindo uma avaliação de risco muito mais robusta.

7.3 Tutorial: Gerando e Visualizando um Mapa de Atenuação

Com base no exemplo do SKA e nas funções atten_map_fast e make_kmz , este tutorial fornece um exemplo de código completo para gerar um mapa de atenuação.  

Passos:

    Definir um transmissor: Localização (longitude, latitude), altura da antena, frequência e potência.

    Definir uma grade de mapa: Um centro de mapa, tamanho em longitude e latitude, e resolução (tamanho do pixel).

    Obter dados de terreno: Use height_map_data para baixar e processar os dados de terreno SRTM para toda a área do mapa.

    Calcular o mapa de atenuação: Use atten_map_fast para calcular a perda de percurso do transmissor para cada pixel no mapa.

    Visualizar o mapa: Use matplotlib para criar um gráfico 2D do mapa de atenuação resultante.

    (Opcional) Exportar para o Google Earth: Use a função make_kmz para criar um arquivo .kmz que pode ser aberto em softwares GIS como o Google Earth, sobrepondo o mapa de atenuação ao terreno real.

Seção 8: Confiabilidade, Validação e Análise Comparativa

Esta seção aborda a questão crucial da confiabilidade da biblioteca e a posiciona no contexto de outras ferramentas disponíveis para análise de propagação de RF.

8.1 Validação através da Padronização

A principal reivindicação de confiabilidade da pycraf reside em sua implementação fiel e "completa" das Recomendações oficiais da UIT-R. O modelo de validação da pycraf é de "conformidade" em vez de "comparação". Enquanto alguns softwares são validados comparando seus resultados com dados experimentais ou com outros softwares confiáveis, a pycraf baseia sua validade na implementação correta de um padrão público, detalhado e internacionalmente aprovado.  

Isso significa que a precisão da pycraf é fundamentalmente a precisão dos próprios modelos da UIT. A "correção" da biblioteca é sua conformidade com os algoritmos do padrão. O conjunto de testes interno, que pode ser executado com pycraf.test() , serve para verificar continuamente essa conformidade, garantindo que o código implemente corretamente as equações dos documentos de padrões em diferentes cenários.  

8.2 Status de Desenvolvimento e Suporte da Comunidade

O projeto pycraf é ativamente mantido, com a versão 2.1.0 sendo o lançamento estável mais recente no momento da redação deste relatório. O desenvolvimento ocorre publicamente no GitHub, que inclui um rastreador de problemas para relatórios de bugs e solicitações de recursos. Este rastreador de problemas oferece transparência sobre o desenvolvimento contínuo da biblioteca, problemas conhecidos e melhorias planejadas (como o suporte solicitado para outras recomendações da UIT, como a P.1812). Além da biblioteca principal, um pacote pycraf-gui também está disponível, fornecendo uma interface gráfica de usuário simples para usuários que preferem uma abordagem visual para os cálculos de atenuação de percurso.  

8.3 Cenário Comparativo

Para fornecer contexto, é útil comparar a pycraf com outras ferramentas de propagação de RF.

    pycraf vs. SPLAT! / PySplat:

        Modelo de Propagação: A pycraf usa a UIT-R P.452. SPLAT! usa o Modelo de Terreno Irregular Longley-Rice. Ambos são modelos empíricos para prever a perda de percurso sobre o terreno, mas são baseados em diferentes conjuntos de dados e formulações.   

Caso de Uso Primário: A pycraf é otimizada para estudos de compatibilidade detalhados entre um número limitado de interferentes e vítimas. SPLAT! e seu invólucro Python, PySplat, são primariamente focados na geração de mapas de cobertura de área ampla para sistemas de transmissão ou repetidores.  

Ecossistema: A pycraf é uma biblioteca Python nativa profundamente integrada com o Astropy. PySplat é um invólucro Python em torno da ferramenta de linha de comando original SPLAT!, que é escrita em C.  

pycraf vs. MATLAB/Simulink (Antenna Toolbox):

    Licenciamento e Custo: A pycraf é de código aberto (GPLv3) e gratuita. O MATLAB é um produto comercial proprietário com custos de licenciamento significativos.   

Escopo: A pycraf é altamente especializada nas Recomendações UIT-R P.452 e P.676. A Antenna Toolbox do MATLAB é um conjunto muito mais amplo que inclui muitos modelos de propagação diferentes (Espaço Livre, Chuva, Gás, Longley-Rice, TIREM, Traçado de Raios) e ferramentas extensas para projeto e análise de antenas.  

        Público-Alvo: A pycraf é adaptada para a comunidade de radioastronomia e gestão de espectro. O MATLAB é uma ferramenta de propósito geral para engenheiros em muitas indústrias.

A tabela a seguir resume essa comparação:

Tabela 1: Comparação de Ferramentas de Propagação de RF
Característica	pycraf	PySplat / SPLAT!	MATLAB Antenna Toolbox
Modelo de Propagação Principal	UIT-R P.452	Longley-Rice	Vários (Longley-Rice, TIREM, Traçado de Raios, etc.)
Licença	GPLv3	GPL	Proprietária
Custo	Gratuito	Gratuito	Comercial (Alto)
Caso de Uso Primário	Estudos de compatibilidade, análise de interferência	Mapeamento de cobertura de área ampla	Engenharia de RF de propósito geral, projeto de sistemas
Integração de Ecossistema	Forte (Python científico, Astropy)	Invólucro de linha de comando	Forte (Ecossistema MATLAB/Simulink)
Principais Pontos Fortes	Conformidade com padrões da UIT, código aberto, precisão física	Geração rápida de mapas de cobertura, longa história	Conjunto abrangente de ferramentas, visualização integrada
Principais Limitações	Foco de nicho, requer configuração de dados externos	Modelo de propagação único, menos flexível para scripts	Custo, software de código fechado

Seção 9: Conclusão e Recomendações

Esta seção final sintetiza as descobertas do relatório em um resumo conciso e oferece recomendações de especialistas para usuários em potencial.

9.1 Resumo das Descobertas

A pycraf se estabelece como uma ferramenta de software especializada, robusta e cientificamente rigorosa, projetada para a tarefa crítica de realizar estudos de compatibilidade de espectro. Suas principais forças residem em:

    Adesão Estrita aos Padrões: Sua implementação fiel das Recomendações da UIT-R (P.452 e P.676) a torna uma ferramenta defensável e confiável para análises regulatórias e científicas.

    Natureza de Código Aberto: A transparência de seu código-fonte promove a confiança e a verificação pela comunidade, posicionando-a como uma base comum para negociações de espectro.

    Integração com o Ecossistema Científico: O uso profundo de Astropy, NumPy e outras bibliotecas padrão a torna uma ferramenta poderosa e flexível dentro de fluxos de trabalho de análise de dados maiores.

    Validação em Projetos de Alto Perfil: Seu uso em projetos de ponta como o SKA demonstra sua capacidade e confiabilidade em cenários do mundo real.

Suas limitações são em grande parte uma consequência de seu foco especializado:

    Escopo de Nicho: Ela não se destina a ser uma ferramenta de engenharia de RF de propósito geral, focando-se primariamente nos modelos da UIT que implementa.

    Requisitos de Configuração: A necessidade de baixar e configurar manualmente os dados de terreno SRTM representa uma barreira inicial para novos usuários.

    Complexidade de Instalação: Para usuários fora do ecossistema Anaconda, a dependência de um compilador C pode complicar a instalação.

9.2 Recomendações de Uso

Com base nesta análise, as seguintes recomendações podem ser feitas:

    Quando usar a pycraf: É a ferramenta ideal para qualquer estudo que exija cálculos verificáveis e em conformidade com os padrões ITU-R P.452 e P.676. Ela se destaca em scripts automatizados, simulações em larga escala (por exemplo, Monte Carlo) e integração em pipelines de análise de dados de radioastronomia. É a escolha preferida para pesquisadores, gerentes de espectro e engenheiros que precisam produzir resultados que possam ser defendidos em um contexto regulatório ou científico.

    Quando considerar alternativas: Para mapeamento de cobertura de RF de propósito geral, onde a conformidade estrita com a P.452 não é um requisito, ferramentas como SPLAT! podem ser mais diretas. Para simulações complexas de multifísica, projeto detalhado de antenas ou em ambientes de engenharia onde o MATLAB é a ferramenta padrão, a Antenna Toolbox pode ser mais apropriada, apesar do custo.

    Melhores Práticas para Usuários: Para garantir o uso bem-sucedido e confiável da pycraf, os usuários devem:

        Utilizar ambientes conda dedicados para gerenciar as dependências e evitar conflitos.

        Baixar os dados de terreno SRTM necessários para sua região de interesse e configurar corretamente a variável de ambiente SRTMDATA.

        Estar ciente da licença de uso não comercial dos dados da UIT incluídos.

        Sempre executar o conjunto de testes (pycraf.test()) após a instalação para verificar se o ambiente está configurado corretamente.

ars.copernicus.org
Spectrum management and compatibility studies with Python - ARS - Volumes
Abre em uma nova janela
ursi.org
References - URSI
Abre em uma nova janela
bwinkel.github.io
pycraf Documentation - GitHub Pages
Abre em uma nova janela
pypi.org
pycraf - PyPI
Abre em uma nova janela
github.com
pycraf is a package that provides functions and procedures for various tasks in spectrum-management compatibility studies. - GitHub
Abre em uma nova janela
pypi.org
pycraf · PyPI
Abre em uma nova janela
researchgate.net
(PDF) Spectrum management and compatibility studies with Python - ResearchGate
Abre em uma nova janela
github.com
bwinkel/pycraf-gui - GitHub
Abre em uma nova janela
arxiv.org
[1805.11434] Spectrum management and compatibility studies with Python - arXiv
Abre em uma nova janela
craf.eu
The newsletter of the ESF Expert Committee on Radio Astronomy Frequencies - CRAF
Abre em uma nova janela
iucaf.org
Python installation guide for IUCAF SMS2025
Abre em uma nova janela
bwinkel.github.io
Installation — pycraf v2.1.0 - GitHub Pages
Abre em uma nova janela
bwinkel.github.io
Protection levels (pycraf.protection) - GitHub Pages
Abre em uma nova janela
bwinkel.github.io
Path attenuation, terrain data, and geodesics (pycraf.pathprof) - GitHub Pages
Abre em uma nova janela
bwinkel.github.io
Antenna patterns (pycraf.antenna) - GitHub Pages
Abre em uma nova janela
bwinkel.github.io
Conversions - pycraf v2.1.0 - GitHub Pages
Abre em uma nova janela
bwinkel.github.io
Conversions (pycraf.conversions) — pycraf v2.1.1.dev1 - GitHub Pages
Abre em uma nova janela
bwinkel.github.io
Atmospheric models (pycraf.atm) — pycraf v2.1.1.dev1 - GitHub Pages
Abre em uma nova janela
bwinkel.github.io
Atmospheric models (pycraf.atm) - GitHub Pages
Abre em uma nova janela
pypi.org
pycraf - PyPI
Abre em uma nova janela
developer.skatelescope.org
Propagation attenuation with Pycraf - SKA telescope developer portal
Abre em uma nova janela
bwinkel.github.io
atten_path_fast — pycraf v2.1.0 - GitHub Pages
Abre em uma nova janela
developer.skao.int
Simulation of visibility with RASCIL — developer.skatelescope.org 0.1.0-beta documentation
Abre em uma nova janela
github.com
Issues · bwinkel/pycraf - GitHub
Abre em uma nova janela
en.wikipedia.org
SPLAT! - Wikipedia
Abre em uma nova janela
github.com
pointhi/PySplat: Doing RF calculations using python and SPLAT - GitHub
Abre em uma nova janela
jfearn.fedorapeople.org
5. Antenna and Propagation Modeling
Abre em uma nova janela
qsl.net
SPLAT! A Terrestrial RF Path Analysis Application For Linux/Unix - QSL.net
Abre em uma nova janela
mathworks.com
RF Propagation - MATLAB & Simulink - MathWorks
