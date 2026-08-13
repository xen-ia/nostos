<!--
  TEMPLATE — knowledge base Nostos (src/knowledge/)

  Un file = un viaggio realmente fatto, non una destinazione generica.
  Naming file: <destinazioni>_<anno-mese>.md, es. sicilia_orientale_2025-10.md
  Se lo stesso posto viene rivisitato, si crea un NUOVO file (non si
  aggiorna questo in place) per preservare l'evoluzione nel tempo.

  Regole per chi scrive:
  - Ogni ### deve reggersi da solo: verrà retrievato come chunk isolato,
    quindi niente "come detto sopra" o riferimenti ad altre sezioni.
  - Scrivere esperienza vissuta in prima persona, non guida turistica:
    non "quando è meglio andare" in astratto, ma "quando ci siamo
    andati noi e cosa abbiamo trovato davvero".
  - "Cosa abbiamo fatto" e "Da evitare" vogliono nomi propri verificati
    di persona, non categorie generiche.
  - Duplicare l'intero blocco ## <Tappa> per ogni città/luogo toccato
    dal viaggio.
  - I commenti HTML (come questo) vanno rimossi in fase di ingestion,
    prima del chunking/embedding — non devono finire nel testo vettorizzato.
-->

---
viaggio: ""
destinazioni: []
periodo: ""                        # es. "2025-10-05 / 2025-10-14"
stagione: ""                       # es. "autunno"
tipo_viaggio: ""                   # coppia | famiglia | solo | gruppo di amici
viaggio_precedente_correlato: null # path a un file precedente sulla stessa zona, se esiste
autore: ""
ultimo_aggiornamento: ""
---

# <Nome viaggio>

## <Tappa 1>

### Identità e atmosfera
<!-- Cosa rende QUESTO posto se stesso, visto con i vostri occhi. -->

### Come l'abbiamo trovata (stagionalità vissuta)
<!-- Non "meteo tipico del mese" ma: com'era davvero in quel periodo,
     affollamento reale, cosa era aperto/chiuso, luce, temperatura percepita. -->

### Cosa abbiamo fatto
<!-- Attività ed esperienze specifiche vissute in prima persona, con
     nomi propri dove possibile (locali, guide, spiagge, quartieri). -->

### Da evitare
<!-- Errori fatti, delusioni, trappole turistiche incontrate davvero.
     Specifico e tagliente: è il cuore della voce Nostos. -->

### Sostenibilità e impatto locale
<!-- Cosa avete notato sull'impatto del turismo lì, e come vi siete
     mossi per non aggravarlo. -->

### Logistica vissuta
<!-- Solo mobilità interna (non voli): come vi siete spostati davvero,
     tempi reali, cosa rifareste uguale o diverso. -->

## <Tappa 2>

### Identità e atmosfera

### Come l'abbiamo trovata (stagionalità vissuta)

### Cosa abbiamo fatto

### Da evitare

### Sostenibilità e impatto locale

### Logistica vissuta