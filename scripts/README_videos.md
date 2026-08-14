# Grabar los 5 vídeos cortos de ContaApp RH

Guion completo en el artifact "Shorts ContaApp RH". Esto es solo la chuleta técnica
para grabar de verdad.

## Una vez, antes de grabar nada

1. Instala las dependencias del proyecto si no lo están ya (`pip install -r ../requirements.txt`).
2. Genera la base de datos ficticia (solo hace falta una vez; los 5 scripts la reutilizan):
   ```
   py generar_datos_demo.py --db-path video_demo.db
   ```
   Si algún día quieres datos distintos, vuelve a correr este mismo comando -- se regenera
   entera y determinista (misma semilla aleatoria).

## Para cada vídeo

1. Abre tu grabador de pantalla (Xbox Game Bar `Win+Alt+R`, o OBS) -- **todavía no le des a grabar**.
2. Ejecuta el script del vídeo que toque, p.ej.:
   ```
   py video1_turnos.py
   ```
3. El script te pide encuadrar la ventana y pulsar Enter en cuanto le des a grabar de verdad --
   a partir de ahí, todo el ritmo (qué tarda cada pantalla en pantalla) ya está calculado para
   que el vídeo final salga en la duración objetivo.
4. `video3_pdf.py` tiene un tramo manual real (clicar "Descargar PDF...", guardar, abrir el PDF)
   -- la ventana se queda totalmente interactiva mientras tanto, no hace falta volver a la consola.
5. `video5_precio.py` tiene el único paso que no puedo automatizar por ti: desconectar el wifi.
   El script te avisa en el momento exacto.

## Vídeo 1 -- la parte que no sale de la app

Antes de correr `video1_turnos.py`, abre `excel_caotico.html` (está en esta misma carpeta)
en tu navegador normal a pantalla completa y graba esos primeros ~8 segundos por separado --
luego los empalmas en el editor con el resto del vídeo.

## Formato vertical (9:16)

La app es una ventana de escritorio normal (horizontal), no nativamente vertical. Graba tal
cual y recorta/haz zoom a la parte central en el editor (CapCut, o el propio editor de
TikTok/Instagram al subir) -- es lo que ya se hizo con las capturas de la demo web, que
también partían de una ventana de escritorio.

## Archivos

- `video_common.py` -- utilidades compartidas (no se ejecuta directamente).
- `video1_turnos.py` / `video2_irpf.py` / `video3_pdf.py` / `video4_alertas.py` / `video5_precio.py`
- `excel_caotico.html` -- mockup del Excel para el arranque del vídeo 1.
- `video_demo.db` -- base de datos generada, no versionada (ver `.gitignore`).
