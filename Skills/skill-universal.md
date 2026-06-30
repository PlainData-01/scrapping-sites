# SKILL UNIVERSAL — Motor de Identidade Visual
# Versão 2.0 | Agência de Sites para Negócios Locais Brasileiros
#
# USO: Concatenar este arquivo ANTES do briefing do cliente em todo prompt de construção.
# Não é necessário nenhum arquivo adicional por nicho — a Fase 0 deriva as regras
# do nicho automaticamente a partir do briefing.
# Estrutura do prompt: [skill-universal.md] + [briefing do cliente] + [instrução de construção]

---

## PROPÓSITO

Você vai construir um site em Next.js + Tailwind para um negócio local brasileiro.
Seu objetivo não é gerar um site bonito — é gerar um site que só poderia ser daquele
cliente específico. Nenhuma decisão visual deve ser tomada por padrão ou conveniência.
Cada decisão deve ser derivada dos dados reais do briefing.

Execute obrigatoriamente as quatro fases abaixo antes de escrever qualquer linha de código.
Documente o resultado de cada fase em comentários no início do arquivo page.tsx.

---

## FASE 0 — ANÁLISE DO NICHO

Execute esta fase antes de ler o briefing do cliente.
O objetivo é mapear o território de mediocridade desse segmento para que
você saiba exatamente o que evitar — sem depender de regras pré-escritas.

**0.1 CLICHÊS VISUAIS DO NICHO**
Com base no nicho identificado no briefing, responda:
Quais são os 3 elementos visuais mais repetidos em sites desse segmento no Brasil?
Descreva: paleta mais comum, layout mais copiado, copy mais usado.
→ Esses 3 elementos entram automaticamente na lista proibida para este projeto.
  Documente-os explicitamente antes de prosseguir.

**0.2 PALETA PADRÃO DO NICHO**
Qual é a combinação de cores que aparece na maioria dos sites desse segmento?
(ex: "creme + terracota para saúde/bem-estar", "azul-marinho + dourado para advocacia",
"verde + branco para alimentação saudável")
→ Essa combinação é proibida neste projeto. Se a cor dominante do cliente
  se aproximar dela, o acento deve ser obrigatoriamente diferente.

**0.3 HEADLINE PADRÃO DO NICHO**
Qual é a headline genérica que aparece em pelo menos 30% dos sites desse segmento?
(ex: "Transforme seu sorriso", "Soluções sob medida", "Sabor que conquista")
→ Essa frase e qualquer variação próxima são proibidas neste projeto.

**0.4 REFERÊNCIA ANTI-PADRÃO**
Se você fosse construir um site para esse nicho que parecesse de outro segmento
completamente diferente — mas de forma que fizesse sentido e elevasse a percepção
de valor — qual seria esse segmento de referência?
(ex: "uma clínica odontológica que parece uma publicação científica",
"um restaurante que parece um ateliê de design", "uma construtora que parece
um escritório de arquitetura premiado")
→ Use esse cruzamento como norte estético. Não como cópia — como direção.

---

## FASE 1 — EXTRAÇÃO

Leia o briefing e responda com precisão. Não invente dados ausentes — sinalize lacunas.

**1.1 DIFERENCIAL PRIMÁRIO**
Qual é o dado mais específico e insubstituível desse cliente?
Exemplos do que procurar: registro profissional com número (CRO-DF 3797),
anos de atuação com marco (fundado em 1993), volume documentado (21.000 pacientes),
tecnologia exclusiva na região (único com cone beam em Sobradinho), prêmio específico,
publicação em periódico, caso de referência notório.
→ Esse dado vai obrigatoriamente para a headline principal. Se não encontrar nenhum,
  sinalize: "DIFERENCIAL AUSENTE NO BRIEFING — solicitar ao cliente antes de prosseguir."

**1.2 PROVA VISUAL DISPONÍVEL**
Liste todas as imagens do briefing classificando cada uma:
- REAL: tirada no local, pelo cliente, sem produção de estúdio
- GENÉRICA: poderia ser banco de imagem (sorriso perfeito, pessoa posada, fundo branco)
- DOCUMENTAL: diploma, certificado, equipamento real, antes/depois de caso real
As imagens REAL e DOCUMENTAL determinam o tom fotográfico do site.
As imagens GENÉRICAS não devem ser usadas como hero ou destaque — apenas apoio.

**1.3 PERSONALIDADE DO TEXTO ATUAL**
Analise os textos reais extraídos do site atual. Classifique em dois eixos:
- Eixo 1: TÉCNICO (jargão da área, dados, procedimentos) ↔ EMOCIONAL (sentimentos, experiência)
- Eixo 2: FORMAL (distância profissional) ↔ PRÓXIMO (conversa direta)
→ Essa classificação define tipografia e tom do copy gerado.

**1.4 COR DOMINANTE ATUAL**
Identifique a cor que mais aparece nos materiais atuais do cliente (site, logo, materiais).
Anote o hex aproximado ou descreva ("azul-marinho escuro", "verde institucional").
→ Essa cor é o ponto de partida da paleta. Nunca substitua por um padrão de nicho
  sem antes tentar evoluir a cor original.
→ Compare com a paleta padrão do nicho mapeada em 0.2. Se forem próximas,
  o acento deve obrigatoriamente divergir.

**1.5 ESTRUTURA DE SERVIÇOS**
Liste os serviços/produtos reais do cliente como aparecem no briefing.
Identifique se há uma lógica de sequência (protocolo, processo) ou de cardápio (opções paralelas).
→ Sequência → estrutura de timeline ou etapas.
→ Cardápio → estrutura de seleção, não grid de cards com ícone genérico.

---

## FASE 2 — DERIVAÇÃO

Com base nas respostas das Fases 0 e 1, tome as seguintes decisões. Documente cada uma.

**2.1 PALETA**

Parta da cor dominante da 1.4. Faça as seguintes perguntas:
- Essa cor, tornada mais fria, comunica algo mais preciso para esse negócio?
- Essa cor, tornada mais escura, ganha mais autoridade?
- Qual seria um acento que contrasta com ela sem cair nos clichês mapeados em 0.2?

Defina: cor de fundo (hex), cor de texto primário (hex), cor de acento (hex),
cor de acento secundário se necessário (hex).

Regra de ouro: as cores escolhidas, vistas juntas, devem remeter imediatamente
ao negócio específico — não ao segmento genérico. Se remeterem ao segmento,
ajuste o acento até que a combinação seja única.

**2.2 TIPOGRAFIA**

Com base na personalidade do texto (1.3) e na referência anti-padrão (0.4):

TÉCNICO + FORMAL → Display: serif de alto contraste, condensada ou semi-condensada,
presença de publicação científica ou relatório técnico. Corpo: sans-serif completamente
neutra, leitura de laudo, invisível.

TÉCNICO + PRÓXIMO → Display: sans-serif com personalidade geométrica ou humanista,
não Montserrat. Corpo: sans-serif com bom espaçamento, confortável.

EMOCIONAL + FORMAL → Display: serif clássica mas não decorativa, peso médio.
Corpo: serif de texto ou sans-serif open. Nunca Playfair Display — é o default
mais óbvio desse quadrante.

EMOCIONAL + PRÓXIMO → Display: sans-serif humanista com caráter, peso variável.
Corpo: sans-serif legível, tamanho generoso.

Sempre que possível, use fontes da Google Fonts fora do top 20 mais usadas no Brasil.
Proibidas como escolha padrão: Montserrat, Playfair Display, Lora, Merriweather,
Raleway, Open Sans, Roboto, Poppins. Use-as apenas se houver razão específica
derivada do briefing (ex: cliente já usa e trocar causaria inconsistência de marca).

**2.3 LAYOUT E HIERARQUIA**

Identifique qual é o maior diferencial do cliente (resultado da 1.1).
A primeira coisa que o usuário vê deve ser esse diferencial — não um hero genérico.

Mapeie os diferenciais em estruturas:
- Tempo de mercado + volume de casos → headline com número + timeline de história
- Tecnologia exclusiva → demonstração do processo técnico em etapas, não lista de serviços
- Especialização certificada → credencial como elemento visual primário, não rodapé
- Localização + atendimento → mapa integrado com contexto, não card genérico de contato

Defina a sequência de seções justificando cada uma com base nos dados reais do cliente.
Não use a sequência padrão [hero → métricas → serviços → sobre → depoimentos → contato]
a não ser que cada seção seja individualmente justificada pelos dados do briefing.

Verifique também: o layout escolhido se diferencia do layout padrão mapeado em 0.1?
Se não, reestruture.

**2.4 COPY**

Parta da headline genérica proibida mapeada em 0.3 e construa o oposto dela
usando o diferencial primário extraído em 1.1.

Formato obrigatório:
[DADO REAL ESPECÍFICO] + [O QUE ISSO SIGNIFICA PARA QUEM ESTÁ LENDO]

Exemplos do formato correto:
- "31 anos reconstruindo funções mastigatórias em Brasília" (não "Transforme seu sorriso")
- "14 subestações. 6 estados. Energia que não para." (não "Soluções sob medida")
- "Do diagnóstico 3D à prótese definitiva — sob o mesmo teto." (não "Atendimento completo")
- "487 causas trabalhistas. 0 acordos por pressão." (não "Defendemos seus direitos")

Construa os subtítulos e CTAs com o mesmo princípio: dado real > benefício genérico.

---

## FASE 3 — AUTOCRÍTICA

Responda cada pergunta com SIM ou NÃO antes de codificar.
Se qualquer resposta for SIM, corrija o problema identificado e repita a verificação.
Só inicie o código após todas as respostas serem NÃO.

```
[ ] 1. Se eu substituir o nome do cliente pelo nome de um concorrente direto,
       esse design ainda funciona visualmente e narrativamente?
       → SIM = não é específico o suficiente. Refaça a headline e o diferencial visual.

[ ] 2. A headline principal usa alguma palavra da LISTA NEGRA ou se parece com
       a headline genérica do nicho mapeada em 0.3?
       → SIM = reescreva usando o formato [dado real] + [significado].

[ ] 3. A paleta escolhida é igual ou muito similar à paleta padrão do nicho mapeada em 0.2?
       → SIM = ajuste o acento até que a combinação seja única para este cliente.

[ ] 4. O layout segue a sequência padrão mapeada em 0.1 como clichê do nicho?
       → SIM = reestruture pelo menos 3 seções com base nos dados reais do cliente.

[ ] 5. Existe algum elemento decorativo sem função narrativa: arco SVG separador,
       gradiente de fundo, card com ícone genérico centralizado, número flutuante decorativo?
       → SIM = remova ou substitua por elemento derivado do negócio real.

[ ] 6. Alguma imagem planejada para posição de destaque poderia ter vindo de banco de imagem?
       → SIM = substitua por placeholder explícito: [FOTO REAL: descrição do que fotografar].

[ ] 7. As fontes escolhidas estão na lista de proibidas sem justificativa específica do briefing?
       → SIM = escolha alternativa com justificativa derivada da personalidade do texto (1.3).

[ ] 8. As credenciais do cliente (registro profissional, certificações, prêmios) estão
       em posição de destaque no layout ou apenas no rodapé?
       → SIM (apenas no rodapé) = integre ao layout como dado primário.

[ ] 9. O copy usa algum benefício genérico que qualquer concorrente poderia usar?
       → SIM = substitua pelo dado real correspondente do briefing.

[ ] 10. Um usuário que chegasse nesse site sem ver o nome do cliente conseguiria
        identificar a especialidade específica, a cidade e o diferencial em menos de 5 segundos?
        → NÃO = o site ainda não é específico o suficiente.
```

---

## LISTA NEGRA UNIVERSAL

Estas proibições valem para qualquer nicho, qualquer cliente.
Somam-se às proibições específicas derivadas da Fase 0.

### Frases proibidas no copy

```
"Transforme seu [X]"
"Soluções sob medida para o seu [X]"
"Qualidade e confiança desde [ano]"
"Atendimento humanizado"
"Resultados que falam por si"
"A [empresa] que você merece"
"Venha nos conhecer"
"Excelência em [X]"
"Sua [Y] em boas mãos"
"Faça a diferença"
"Cuidamos do seu [X] com carinho"
"[X] de alta qualidade"
"Somos apaixonados por [X]"
"Sua satisfação é nossa prioridade"
"Equipe altamente qualificada"
"Anos de experiência no mercado"     ← use o número real: "31 anos", não "anos de experiência"
"Tecnologia de ponta"                ← cite a tecnologia real, não o eufemismo
"Atendimento personalizado"          ← demonstre com o protocolo real, não declare
```

### Elementos visuais proibidos

```
Arcos ou curvas SVG como separadores decorativos entre seções
Grid de 3 colunas com ícone Lucide/Heroicons centralizado + título + texto curto
Faixa escura (ou colorida) com 3-4 números de credibilidade centralizados
Carrossel de depoimentos com foto redonda + nome + estrelas douradas
Gradiente suave como background de seção (ex: de branco para creme)
Cards com box-shadow suave idêntico em todos os elementos da página
Linha divisória decorativa com ícone centralizado
Número grande flutuante como elemento decorativo sem contexto
Hero com imagem à direita ocupando 40-50% da tela + texto à esquerda
```

### Fontes proibidas como escolha padrão

```
Montserrat         → usada em 40%+ dos sites "modernos" gerados por IA
Playfair Display   → default automático para qualquer coisa "premium" ou "elegante"
Lora               → default para "elegante mas acessível"
Merriweather       → default para "conteúdo sério"
Raleway            → default para "clean e sofisticado"
Poppins            → default para "jovem e moderno"
```
Estas fontes só podem ser usadas se houver razão explícita derivada do briefing.

---

## INSTRUÇÃO DE CONSTRUÇÃO

Após executar as 4 fases e documentar os resultados, siga esta ordem:

1. Crie `/components/tokens.ts` com as variáveis de design derivadas da Fase 2
   (cores, fontes, espaçamentos específicos deste cliente)
2. Crie os componentes na ordem da hierarquia de seções definida em 2.3
3. Em cada componente, o primeiro comentário deve referenciar qual dado do briefing
   justifica aquela seção existir
4. Imagens não disponíveis devem ser substituídas por componentes de placeholder
   explícitos com instrução de fotografia:
   [FOTO REAL NECESSÁRIA: descrição do que deve ser fotografado e por quê importa]

Entregue ao final:
- Código funcional em Next.js + Tailwind
- Arquivo `DESIGN-DECISIONS.md` na raiz documentando cada decisão das Fases 0, 1, 2 e 3
  com a justificativa derivada do briefing
