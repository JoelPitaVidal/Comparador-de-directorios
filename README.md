# Comparador de Directorios Web

Herramienta web para comparar directorios locales y remotos (via SSH/SFTP) con interfaz interactiva.

## Características

- Comparación de directorios local/remoto
- Hash SHA256 para detectar cambios de contenido
- Visualización de diferencias linea por linea
- Interfaz web interactiva
- Servidor persistente para múltiples comparaciones
- Autenticación SSH por contraseña o clave privada
- Soporte automático para claves PPK (PuTTY)
- Filtros por estado de archivo
- Estadísticas detalladas

## Requisitos

### Python
- Python 3.7 o superior

### Dependencias
```bash
pip install paramiko cryptography
```

### Windows (para conversión automática de .ppk)
- PuTTY instalado (https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html)
  - O Git Bash instalado (https://git-scm.com/download/win)

## Instalación

### Paso 1: Descargar programa

Descarga el archivo `directory_comparator_web.py`

### Paso 2: Instalar dependencias

```bash
pip install -r requirements.txt
```

O instala manualmente:
```bash
pip install paramiko cryptography
```

### Paso 3: Instalar PuTTY (Windows)

Para uso automático de claves .ppk:

1. Descarga PuTTY: https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html
2. Ejecuta instalador: `putty-64bit-X.XX-installer.msi`
3. Durante instalación, marca "Add PuTTY to PATH"
4. Reinicia Windows

Alternativa: Instala Git Bash (incluye ssh-keygen)

## Uso

### Ejecución básica

```bash
python directory_comparator_web.py
```

El navegador se abrirá automáticamente en: http://127.0.0.1:[puerto]

### Ejecución con parámetros

```bash
python directory_comparator_web.py --port 8000 --host 0.0.0.0
```

- `--port`: Puerto a usar (default: automático)
- `--host`: Host a escuchar (default: 127.0.0.1)

### Interfaz Web

1. Completa los campos:
   - Ruta Local: Ruta del directorio local
   - Ruta Remota: Ruta del directorio remoto
   - Remoto (SSH/SFTP): Marca si es conexión remota

2. Si es remoto, proporciona:
   - Host SSH: servidor.com o IP
   - Usuario: nombre de usuario
   - Puerto: 22 (por defecto)
   - Autenticación:
     - Contraseña: Tu contraseña SSH
     - O Clave privada: Ruta al archivo de clave (~/.ssh/id_rsa, dev26.rodavigo, etc)

3. Presiona "Comparar Directorios"

4. Resultados:
   - Total de archivos
   - Idénticos: Mismo contenido en ambos lados
   - Diferentes: Existe en ambos pero con contenido diferente
   - Falta en remoto: Solo existe en directorio local
   - Falta en local: Solo existe en directorio remoto

5. Haz clic en un archivo para ver:
   - Estado detallado
   - Diferencias linea por linea (si está modificado)

## Claves SSH

### Formatos soportados

- OpenSSH (estándar, recomendado)
- PEM
- PPK (PuTTY) - se convierte automáticamente

### Conversión automática de .ppk

Si usas clave en formato .ppk:

1. El programa intenta:
   - Ejecutar puttygen.exe (si PuTTY está instalado)
   - Ejecutar ssh-keygen (si Git Bash está instalado)
   - Parser custom (último intento)

2. Si todo falla, convierte manualmente:
   - Abre PuTTYgen
   - Load -> tu_archivo.ppk
   - Conversions -> Export OpenSSH key
   - Guarda sin extensión .ppk
   - Usa archivo convertido en el programa

### Conversión manual de .ppk

Si necesitas convertir manualmente:

```bash
# Con PuTTYgen (Windows)
puttygen.exe -i archivo.ppk -O private-openssh -o archivo_convertido

# Con ssh-keygen (Linux/Mac/Git Bash)
ssh-keygen -i -f archivo.ppk -m pem > archivo_convertido
```

## Autenticación SSH

El programa intenta autenticación en este orden:

1. Contraseña (si la proporcionas)
2. Clave privada (si especificas ruta)
3. SSH-Agent (si está configurado)
4. Claves por defecto (~/.ssh/id_rsa, etc)

Puedes dejar contraseña y clave vacías para usar ssh-agent o claves por defecto.

## Estructura de archivos

```
.
├── directory_comparator_web.py      # Programa principal
├── requirements.txt                  # Dependencias
├── README.md                         # Este archivo
├── COMENTARIOS_CODIGO.txt           # Explicación del código
├── CONVERTER_STANDALONE_INSTRUCCIONES.txt
├── CONVERSION_MEJORADA_PPK.md
├── convertir_ppk_standalone.py      # Script conversor PPK (opcional)
└── README_WEB.md                    # Guía interfaz web
```

## Ejemplos de uso

### Comparar directorios locales (Windows)

```
Ruta Local: C:/Users/usuario/Documentos/Proyecto
Ruta Remota: C:/Users/usuario/Documentos/ProyectoBackup
Remoto: NO marcado
```

### Comparar directorios locales (Linux)

```
Ruta Local: ~/proyectos/codigo
Ruta Remota: ~/proyectos/codigo_backup
Remoto: NO marcado
```

### Comparar con servidor remoto via SSH

```
Ruta Local: C:/Code/dev26/app/Language/es
Ruta Remota: /home/usuario/web/app/Language/it
Remoto: MARCADO
Host SSH: 10.10.29.152
Usuario: usuario
Puerto: 22
Autenticacion: Clave privada
Ruta de Clave: C:/Users/usuario/Desktop/Claves/dev26.rodavigo
```

## Troubleshooting

### Error: "Paramiko no instalado"

Solución:
```bash
pip install paramiko
```

### Error: "No se puede procesar archivo PPK"

Opciones:

1. Instala PuTTY (https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html)
   - Marca "Add PuTTY to PATH" durante instalación
   - Reinicia Windows

2. O instala Git Bash (https://git-scm.com/download/win)
   - Incluye ssh-keygen automáticamente

3. O convierte manualmente:
   - Abre PuTTYgen
   - Load -> archivo.ppk
   - Conversions -> Export OpenSSH key
   - Guarda sin extensión .ppk

### Error: "Host no alcanzable"

Verifica:
- Host SSH es correcto
- Usuario es correcto
- Servidor SSH está activo
- Puerto 22 está abierto (o el puerto especificado)
- Tienes conectividad de red

### Error: "Autenticación fallida"

Verifica:
- Contraseña es correcta (si usas autenticación por contraseña)
- Ruta de clave es correcta (si usas clave privada)
- Usuario tiene permisos en servidor
- Clave privada está en formato correcto (OpenSSH o PEM)

### El servidor no se abre automáticamente

El servidor está funcionando, abre manualmente en tu navegador:
```
http://127.0.0.1:PUERTO
```

Donde PUERTO es el número mostrado en consola.

## Preguntas frecuentes

### ¿Necesito hacer algo con la clave privada?

No. La clave privada:
- NO se modifica
- NO se envía a internet
- NO se expone
- Solo se usa localmente para autenticación SSH

### ¿Qué significa cada estado de archivo?

- **Idéntico**: Mismo contenido (mismo hash SHA256) en ambos lados
- **Contenido diferente**: Existe en ambos pero con contenido diferente
- **Falta en remoto**: Existe en directorio local pero no en remoto
- **Falta en local**: Existe en directorio remoto pero no en local

### ¿Puedo hacer múltiples comparaciones?

Sí. El servidor se mantiene activo. Puedes:
- Hacer otra comparación
- Cambiar rutas
- Cambiar servidor SSH
- Todo sin reiniciar el programa

Presiona "Limpiar" para resetear formulario.

### ¿Es seguro conectarse a servidor remoto?

Sí:
- SSH cifra toda comunicación
- Autenticación por clave privada es segura
- El programa no guarda contraseñas
- Conexión se cierra después de cada comparación

### ¿Puedo comparar directorios muy grandes?

Sí, pero:
- Calcula hash de cada archivo (puede tomar tiempo)
- Lee archivos en bloques (eficiente)
- No descarga archivos completos innecesariamente
- Para miles de archivos, puede tomar minutos

### ¿Qué ocurre si hay archivos grandes?

El programa:
- Calcula hash en bloques de 4KB
- No carga archivo completo en memoria
- Es eficiente incluso con archivos de GB

## Licencia

Este programa es de uso libre. Modifica y distribuye libremente.

## Soporte

Para problemas o sugerencias, revisa:
- Este README
- COMENTARIOS_CODIGO.txt
- README_WEB.md

## Notas técnicas

### Algoritmo de comparación

1. Lista archivos en directorio local
2. Lista archivos en directorio remoto
3. Para cada archivo:
   - Si existe en ambos: calcula hash SHA256
   - Si hashes son iguales: estado "idéntico"
   - Si hashes diferentes: estado "contenido diferente"
   - Si solo en local: estado "falta en remoto"
   - Si solo en remoto: estado "falta en local"

### Conversión de claves PPK

El programa intenta estos métodos en orden:

1. puttygen.exe (si PuTTY está instalado en PATH)
2. ssh-keygen (si está disponible)
3. Parser custom Python (último intento)

Si todos fallan, se sugiere conversión manual con PuTTYgen.

### Seguridad

- SSH cifra toda comunicación
- Claves privadas nunca se transmiten
- Permisos de archivo temporal: 600 (solo lectura propietario)
- Conexiones se cierran apropiadamente
- Sin almacenamiento de credenciales

## Versión

Versión 1.0 - Junio 2026

---

Listo para usar. Ejecución:

```bash
python directory_comparator_web.py
```

El navegador se abrirá automáticamente.