"""
aliases_500kv.py
Diccionario de aliases para traducir tokens del campo Nombre de lineas GeoSADI
al nombre canonico de la estacion (name_geosadi normalizado).

Las claves son exactamente como quedan los tokens tras normalize():
    sin tildes, mayusculas, sin puntuacion, espacios simples.
    Se incluye la version SIN espacios (token concatenado) Y
    la version CON espacios (token_sp) porque el script 04
    busca ambas en cada ventana deslizante.

Razon de los aliases de "identidad" (valor == clave):
    Los nombres de estacion de multiples palabras (GRAN PARANA, SANTO TOME, etc.)
    no matchean solos porque el sliding window los parte en tokens individuales.
    El alias de identidad hace que el window de N palabras los capture como unidad.

Mantenimiento:
    Agregar entradas cuando aparezcan nuevos sin_match al correr el script 04.
    El reporte muestra los tokens [BUS_I] — [BUS_J] para guiar el diagnostico.
"""

ALIASES = {

    # -------------------------------------------------------------------------
    # PUERTO MADRYN
    # GeoSADI: "N.P.MADRYN" -> tokens: N, P, MADRYN
    # -------------------------------------------------------------------------
    'N P MADRYN'       : 'PUERTO MADRYN',
    'NPMADRYN'         : 'PUERTO MADRYN',

    # -------------------------------------------------------------------------
    # SANTA CRUZ NORTE / RIO SANTA CRUZ / ESPERANZA PAT
    # GeoSADI: "SANTA CRUZ NORTE", "RIO SANTA CRUZ", "ESPERANZA PAT"
    # -------------------------------------------------------------------------
    'SANTA CRUZ NORTE' : 'SANTA CRUZ NORTE',
    'SANTACRUZNORTE'   : 'SANTA CRUZ NORTE',
    'RIO SANTA CRUZ'   : 'RIO SANTA CRUZ',
    'RIOSANTACRUZ'     : 'RIO SANTA CRUZ',
    'ESPERANZA PAT'    : 'ESPERANZA PAT',
    'ESPERANZAPAT'     : 'ESPERANZA PAT',

    # -------------------------------------------------------------------------
    # CERRITO DE LA COSTA
    # GeoSADI: "C.COSTA" -> tokens: C, COSTA
    # -------------------------------------------------------------------------
    'C COSTA'          : 'CERRITO DE LA COSTA',
    'CCOSTA'           : 'CERRITO DE LA COSTA',

    # -------------------------------------------------------------------------
    # P. DEL AGUILA CH  (central hidroelectrica)
    # GeoSADI: "C.P.AGUILA" -> tokens: C, P, AGUILA
    # -------------------------------------------------------------------------
    'C P AGUILA'       : 'P DEL AGUILA CH',
    'CPAGUILA'         : 'P DEL AGUILA CH',

    # -------------------------------------------------------------------------
    # P. DEL AGUILA  (estacion transformadora)
    # GeoSADI: "ET.P.AGUILA" -> tokens: ET, P, AGUILA
    # -------------------------------------------------------------------------
    'ET P AGUILA'      : 'P DEL AGUILA',
    'ETPAGUILA'        : 'P DEL AGUILA',

    # -------------------------------------------------------------------------
    # EL CHOCON OESTE
    # GeoSADI: "CHOCON OESTE" -> tokens: CHOCON, OESTE
    # -------------------------------------------------------------------------
    'CHOCON OESTE'     : 'EL CHOCON OESTE',
    'CHOCONOESTE'      : 'EL CHOCON OESTE',

    # -------------------------------------------------------------------------
    # EL CHOCON
    # GeoSADI: "CHOCON" solo (sin EL)
    # -------------------------------------------------------------------------
    'CHOCON'           : 'EL CHOCON',

    # -------------------------------------------------------------------------
    # EL CHOCON CH  (casa de maquinas)
    # -------------------------------------------------------------------------
    'C H CHOCON'       : 'EL CHOCON CH',
    'CHCHOCON'         : 'EL CHOCON CH',

    # -------------------------------------------------------------------------
    # CHOELE CHOEL
    # GeoSADI: "CHOELE CHOEL" -> tokens: CHOELE, CHOEL
    # -------------------------------------------------------------------------
    'CHOELE CHOEL'     : 'CHOELE CHOEL',
    'CHOELCHOEL'       : 'CHOELE CHOEL',
    'CHOELE'           : 'CHOELE CHOEL',   # para "PI608 CHOELE"

    # -------------------------------------------------------------------------
    # AGUA DE CAJON
    # GeoSADI: "AGUA CAJON" -> tokens: AGUA, CAJON
    # -------------------------------------------------------------------------
    'AGUA CAJON'       : 'AGUA DE CAJON',
    'AGUACAJON'        : 'AGUA DE CAJON',

    # -------------------------------------------------------------------------
    # LOMA LA LATA
    # GeoSADI: "LOMA LATA" -> tokens: LOMA, LATA
    # -------------------------------------------------------------------------
    'LOMA LATA'        : 'LOMA LA LATA',
    'LOMALATA'         : 'LOMA LA LATA',

    # -------------------------------------------------------------------------
    # P BANDERITA
    # GeoSADI: "P.BANDERITA" -> tokens: P, BANDERITA
    # -------------------------------------------------------------------------
    'P BANDERITA'      : 'P BANDERITA',
    'PBANDERITA'       : 'P BANDERITA',

    # -------------------------------------------------------------------------
    # P P LEUFU
    # -------------------------------------------------------------------------
    'P P LEUFU'        : 'P P LEUFU',
    'PPLEUFU'          : 'P P LEUFU',

    # -------------------------------------------------------------------------
    # G BROWN
    # GeoSADI: "G.BROWN" -> tokens: G, BROWN
    #          "CT G. BROWN" -> tokens: CT, G, BROWN
    # -------------------------------------------------------------------------
    'G BROWN'          : 'G BROWN',
    'GBROWN'           : 'G BROWN',
    'CT G BROWN'       : 'G BROWN',
    'CTGBROWN'         : 'G BROWN',

    # -------------------------------------------------------------------------
    # PI608 (nodo intermedio, ignorar)
    # -------------------------------------------------------------------------
    'PI608'            : None,

    # -------------------------------------------------------------------------
    # BAHIA BLANCA
    # GeoSADI: "BAHIA BLANCA" -> tokens: BAHIA, BLANCA
    #          "B.BLANCA" -> tokens: B, BLANCA
    # -------------------------------------------------------------------------
    'BAHIA BLANCA'     : 'BAHIA BLANCA',
    'BAHIABLANCA'      : 'BAHIA BLANCA',
    'B BLANCA'         : 'BAHIA BLANCA',
    'BBLANCA'          : 'BAHIA BLANCA',

    # -------------------------------------------------------------------------
    # PIEDRA BUENA
    # GeoSADI: "C.PIEDRABUENA" -> tokens: C, PIEDRABUENA
    #          "CTPBUENA", "CPBUENA" -> variantes abreviadas
    # -------------------------------------------------------------------------
    'C PIEDRABUENA'    : 'PIEDRA BUENA',
    'CPIEDRABUENA'     : 'PIEDRA BUENA',
    'CTPBUENA'         : 'PIEDRA BUENA',
    'CPBUENA'          : 'PIEDRA BUENA',

    # -------------------------------------------------------------------------
    # C ELIA
    # GeoSADI: "COLONIA ELIA" -> tokens: COLONIA, ELIA
    # -------------------------------------------------------------------------
    'COLONIA ELIA'     : 'C ELIA',
    'COLONIAELIA'      : 'C ELIA',

    # -------------------------------------------------------------------------
    # MANUEL BELGRANO
    # GeoSADI: "M.BELGRANO" -> tokens: M, BELGRANO
    # -------------------------------------------------------------------------
    'M BELGRANO'       : 'MANUEL BELGRANO',
    'MBELGRANO'        : 'MANUEL BELGRANO',

    # -------------------------------------------------------------------------
    # NUEVA CAMPANA
    # GeoSADI: "N.CAMPANA" -> tokens: N, CAMPANA
    # -------------------------------------------------------------------------
    'N CAMPANA'        : 'NUEVA CAMPANA',
    'NCAMPANA'         : 'NUEVA CAMPANA',

    # -------------------------------------------------------------------------
    # GRAL RODRIGUEZ
    # GeoSADI: "G.RODRIGUEZ" -> tokens: G, RODRIGUEZ
    # -------------------------------------------------------------------------
    'G RODRIGUEZ'      : 'GRAL RODRIGUEZ',
    'GRODRIGUEZ'       : 'GRAL RODRIGUEZ',

    # -------------------------------------------------------------------------
    # CENTRAL GENELBA
    # -------------------------------------------------------------------------
    'GENELBA'          : 'CENTRAL GENELBA',

    # -------------------------------------------------------------------------
    # SALTO GRANDE ARG
    # GeoSADI: "SGDE.ARG" -> tokens: SGDE, ARG
    #          "SALTO GRANDE ARG" -> tokens: SALTO, GRANDE, ARG
    # -------------------------------------------------------------------------
    'SGDE ARG'         : 'SALTO GRANDE ARG',
    'SGDEARG'          : 'SALTO GRANDE ARG',
    'SALTO GRANDE ARG' : 'SALTO GRANDE ARG',
    'SALTOGRANDEARG'   : 'SALTO GRANDE ARG',

    # -------------------------------------------------------------------------
    # SANTO TOME
    # GeoSADI: "SANTO TOME" -> tokens: SANTO, TOME
    # -------------------------------------------------------------------------
    'SANTO TOME'       : 'SANTO TOME',
    'SANTOTOME'        : 'SANTO TOME',

    # -------------------------------------------------------------------------
    # ROSARIO OESTE
    # GeoSADI: "ROSARIO OESTE" -> tokens: ROSARIO, OESTE
    #          "R.OESTE" -> tokens: R, OESTE
    # -------------------------------------------------------------------------
    'ROSARIO OESTE'    : 'ROSARIO OESTE',
    'ROSARIOOESTE'     : 'ROSARIO OESTE',
    'R OESTE'          : 'ROSARIO OESTE',
    'ROESTE'           : 'ROSARIO OESTE',

    # -------------------------------------------------------------------------
    # RIO CORONDA
    # GeoSADI: "RIO CORONDA" -> tokens: RIO, CORONDA
    # -------------------------------------------------------------------------
    'RIO CORONDA'      : 'RIO CORONDA',
    'RIOCORONDA'       : 'RIO CORONDA',

    # -------------------------------------------------------------------------
    # RINCON STA MARIA
    # GeoSADI: "RINCON" solo
    # -------------------------------------------------------------------------
    'RINCON'           : 'RINCON STA MARIA',

    # -------------------------------------------------------------------------
    # AES PARANA
    # GeoSADI: "AES.PARANA" -> tokens: AES, PARANA
    # -------------------------------------------------------------------------
    'AES PARANA'       : 'AES PARANA',
    'AESPARANA'        : 'AES PARANA',

    # -------------------------------------------------------------------------
    # GRAN PARANA
    # GeoSADI: "GRAN PARANA" -> tokens: GRAN, PARANA
    # -------------------------------------------------------------------------
    'GRAN PARANA'      : 'GRAN PARANA',
    'GRANPARANA'       : 'GRAN PARANA',

    # -------------------------------------------------------------------------
    # ARROYO CABRAL
    # GeoSADI: "ARROYO CABRAL" -> tokens: ARROYO, CABRAL
    # -------------------------------------------------------------------------
    'ARROYO CABRAL'    : 'ARROYO CABRAL',
    'ARROYOCABRAL'     : 'ARROYO CABRAL',

    # -------------------------------------------------------------------------
    # SAN ISIDRO
    # GeoSADI: "SAN ISIDRO" -> tokens: SAN, ISIDRO
    # -------------------------------------------------------------------------
    'SAN ISIDRO'       : 'SAN ISIDRO',
    'SANISIDRO'        : 'SAN ISIDRO',

    # -------------------------------------------------------------------------
    # GRAN FORMOSA
    # GeoSADI: "GRAN FORMOSA" -> tokens: GRAN, FORMOSA
    # -------------------------------------------------------------------------
    'GRAN FORMOSA'     : 'GRAN FORMOSA',
    'GRANFORMOSA'      : 'GRAN FORMOSA',

    # -------------------------------------------------------------------------
    # ATUCHA II
    # GeoSADI: "ATUCHA II" -> tokens: ATUCHA, II
    # -------------------------------------------------------------------------
    'ATUCHA II'        : 'ATUCHA II',
    'ATUCHAII'         : 'ATUCHA II',

    # -------------------------------------------------------------------------
    # 25 DE MAYO
    # GeoSADI: "25 DE MAYO" -> tokens: 25, DE, MAYO
    # -------------------------------------------------------------------------
    '25 DE MAYO'       : '25 DE MAYO',
    '25DEMAYO'         : '25 DE MAYO',

    # -------------------------------------------------------------------------
    # EL BRACHO
    # GeoSADI: "EL BRACHO" -> tokens: EL, BRACHO
    # -------------------------------------------------------------------------
    'EL BRACHO'        : 'EL BRACHO',
    'ELBRACHO'         : 'EL BRACHO',

    # -------------------------------------------------------------------------
    # LA RIOJA SUR
    # GeoSADI: "LA RIOJA SUR" -> tokens: LA, RIOJA, SUR
    # -------------------------------------------------------------------------
    'LA RIOJA SUR'     : 'LA RIOJA SUR',
    'LARIOJASUR'       : 'LA RIOJA SUR',

    # -------------------------------------------------------------------------
    # SAN JUANCITO
    # GeoSADI: "SAN JUANCITO" -> tokens: SAN, JUANCITO
    # -------------------------------------------------------------------------
    'SAN JUANCITO'     : 'SAN JUANCITO',
    'SANJUANCITO'      : 'SAN JUANCITO',

    # -------------------------------------------------------------------------
    # SANTIAGO (del Estero)
    # GeoSADI: "STGO DEL ESTERO" -> tokens: STGO, DEL, ESTERO
    # -------------------------------------------------------------------------
    'STGO DEL ESTERO'  : 'SANTIAGO',
    'STGODELESTERO'    : 'SANTIAGO',

    # -------------------------------------------------------------------------
    # GRAN MENDOZA
    # -------------------------------------------------------------------------
    'GRAN MENDOZA'     : 'GRAN MENDOZA',
    'GRANMENDOZA'      : 'GRAN MENDOZA',

    # -------------------------------------------------------------------------
    # NUEVA SAN JUAN
    # -------------------------------------------------------------------------
    'NUEVA SAN JUAN'   : 'NUEVA SAN JUAN',
    'NUEVASANJUAN'     : 'NUEVA SAN JUAN',

    # -------------------------------------------------------------------------
    # EL CHOCON OESTE — variante sin espacios usada en GeoSADI
    # -------------------------------------------------------------------------
    'CHOCONOE'         : 'EL CHOCON OESTE',

    # -------------------------------------------------------------------------
    # C ELIA — alias de identidad para que el window lo capture como unidad
    # GeoSADI: "C.ELIA" -> tokens: C, ELIA
    # -------------------------------------------------------------------------
    'C ELIA'           : 'C ELIA',
    'CELIA'            : 'C ELIA',

    # -------------------------------------------------------------------------
    # SANTO TOME — variante abreviada S.TOME
    # GeoSADI: "S.TOME" -> tokens: S, TOME
    # -------------------------------------------------------------------------
    'S TOME'           : 'SANTO TOME',
    'STOME'            : 'SANTO TOME',

    # -------------------------------------------------------------------------
    # PASO LA PATRIA — variante P.PATRIA
    # GeoSADI: "P.PATRIA" -> tokens: P, PATRIA
    # -------------------------------------------------------------------------
    'P PATRIA'         : 'PASO LA PATRIA',
    'PPATRIA'          : 'PASO LA PATRIA',

    # -------------------------------------------------------------------------
    # MALVINAS — GeoSADI usa MALVINCO
    # -------------------------------------------------------------------------
    'MALVINCO'         : 'MALVINAS',

    # -------------------------------------------------------------------------
    # RIO GRANDE — variante R.GRANDE
    # GeoSADI: "R.GRANDE" -> tokens: R, GRANDE
    # -------------------------------------------------------------------------
    'R GRANDE'         : 'RIO GRANDE',
    'RGRANDE'          : 'RIO GRANDE',

    # -------------------------------------------------------------------------
    # LUJAN — variante LUJAN.SL
    # GeoSADI: "LUJAN.SL" -> tokens: LUJAN, SL
    # -------------------------------------------------------------------------
    'LUJAN SL'         : 'LUJAN',
    'LUJANSL'          : 'LUJAN',

    # -------------------------------------------------------------------------
    # GRAN MENDOZA — variante GRAN MZA (con espacios)
    # -------------------------------------------------------------------------
    'GRAN MZA'         : 'GRAN MENDOZA',
    'GRANMZA'          : 'GRAN MENDOZA',

    # -------------------------------------------------------------------------
    # Tokens a ignorar (prefijos institucionales o nodos sin estacion propia)
    # -------------------------------------------------------------------------
    'LIMITE'           : None,
    'ARG BRA'          : None,
    'URU'              : None,
}
