#!/usr/bin/env python3
"""
Ejemplos de uso del comparador de directorios
"""

# ============================================================================
# EJEMPLO 1: USO VÍA LÍNEA DE COMANDOS (CLI)
# ============================================================================

"""
Comparar dos directorios locales:
$ python directory_comparator.py ~/carpeta1 ~/carpeta2

Comparar con servidor remoto (SFTP):
$ python directory_comparator.py ~/local /datos \
    --ssh-host servidor.rodavigo.com \
    --ssh-user deploy \
    --ssh-key ~/.ssh/rodavigo_key

Comparar catálogos en diferentes idiomas:
$ python directory_comparator.py ~/catalogs/es ~/catalogs/en

Con puerto web personalizado:
$ python directory_comparator.py ~/local ~/remoto --port 8000
"""


# ============================================================================
# EJEMPLO 2: USO DESDE PYTHON SCRIPT
# ============================================================================

from directory_comparator import DirectoryComparator, FileStatus

def ejemplo_comparacion_basica():
    """Ejemplo básico: comparar dos directorios locales"""
    
    print("=" * 70)
    print("EJEMPLO 1: Comparación básica de directorios locales")
    print("=" * 70)
    
    # Crear comparador
    comparador = DirectoryComparator(
        local_path='~/mi_proyecto/local',
        remote_path='~/mi_proyecto/remoto'
    )
    
    # Ejecutar comparación
    resultados = comparador.compare()
    
    # Analizar resultados
    print(f"\nTotal de archivos: {len(resultados)}")
    
    # Agrupar por estado
    por_estado = {}
    for rel_path, info in resultados.items():
        estado = info.status
        if estado not in por_estado:
            por_estado[estado] = []
        por_estado[estado].append(rel_path)
    
    # Mostrar resumen
    print("\n📊 RESUMEN:")
    for estado, archivos in por_estado.items():
        print(f"  {estado}: {len(archivos)} archivos")
    
    # Mostrar archivos diferentes
    print("\n📋 ARCHIVOS CON DIFERENCIAS:")
    archivos_diferentes = por_estado.get('contenido diferente', [])
    for archivo in archivos_diferentes[:10]:  # Primeros 10
        print(f"  - {archivo}")
    
    comparador.close()


def ejemplo_ver_diffs():
    """Ejemplo: Visualizar diferencias específicas de archivos"""
    
    print("\n" + "=" * 70)
    print("EJEMPLO 2: Visualizar diferencias de contenido")
    print("=" * 70)
    
    comparador = DirectoryComparator('~/local', '~/remoto')
    resultados = comparador.compare()
    
    # Encontrar archivos con diferencias
    archivos_diferentes = [
        path for path, info in resultados.items() 
        if info.status == 'contenido diferente'
    ]
    
    if archivos_diferentes:
        archivo = archivos_diferentes[0]
        print(f"\nMostrando diferencias de: {archivo}\n")
        
        diff = comparador.get_diff(archivo)
        # Mostrar solo primeras 50 líneas
        lineas = diff.split('\n')[:50]
        print('\n'.join(lineas))
        
        if len(diff.split('\n')) > 50:
            print(f"\n... ({len(diff.split(chr(10))) - 50} líneas más)")
    
    comparador.close()


def ejemplo_filtrado_selectivo():
    """Ejemplo: Filtrar por tipo de diferencia"""
    
    print("\n" + "=" * 70)
    print("EJEMPLO 3: Análisis filtrado de resultados")
    print("=" * 70)
    
    comparador = DirectoryComparator('~/local', '~/remoto')
    resultados = comparador.compare()
    
    # Archivos solo en local
    print("\n📁 Archivos solo en LOCAL (no están en remoto):")
    solo_local = [path for path, info in resultados.items() 
                  if info.status == 'falta en remoto']
    for archivo in solo_local[:5]:
        print(f"  - {archivo}")
    if len(solo_local) > 5:
        print(f"  ... y {len(solo_local) - 5} más")
    
    # Archivos solo en remoto
    print("\n📁 Archivos solo en REMOTO (no están en local):")
    solo_remoto = [path for path, info in resultados.items() 
                   if info.status == 'falta en local']
    for archivo in solo_remoto[:5]:
        print(f"  - {archivo}")
    if len(solo_remoto) > 5:
        print(f"  ... y {len(solo_remoto) - 5} más")
    
    # Resumen
    print(f"\n✓ Idénticos: {len([p for p, i in resultados.items() if i.status == 'idéntico'])}")
    print(f"⚠️ Diferentes: {len([p for p, i in resultados.items() if i.status == 'contenido diferente'])}")
    print(f"✗ Faltantes: {len(solo_local) + len(solo_remoto)}")
    
    comparador.close()


def ejemplo_con_ssh():
    """Ejemplo: Comparar con servidor remoto vía SSH"""
    
    print("\n" + "=" * 70)
    print("EJEMPLO 4: Comparación con servidor remoto (SSH/SFTP)")
    print("=" * 70)
    
    # Configuración SSH
    ssh_config = {
        'hostname': 'produccion.rodavigo.com',
        'username': 'deploy',
        'key_file': '/home/usuario/.ssh/rodavigo_key',
        'port': 22
    }
    
    try:
        comparador = DirectoryComparator(
            local_path='~/aplicacion/local',
            remote_path='/var/www/aplicacion',
            ssh_config=ssh_config
        )
        
        print("✓ Conectado al servidor remoto")
        
        resultados = comparador.compare()
        print(f"✓ Comparación completada: {len(resultados)} archivos analizados")
        
        # Mostrar resumen rápido
        diferentes = [p for p, i in resultados.items() if i.status == 'contenido diferente']
        print(f"⚠️ Archivos con diferencias: {len(diferentes)}")
        
        comparador.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")


def ejemplo_exportar_reporte():
    """Ejemplo: Generar reporte exportable"""
    
    print("\n" + "=" * 70)
    print("EJEMPLO 5: Exportar resultados a archivo")
    print("=" * 70)
    
    comparador = DirectoryComparator('~/local', '~/remoto')
    resultados = comparador.compare()
    
    # Exportar a CSV
    import csv
    with open('reporte_comparacion.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Archivo', 'Estado', 'En Local', 'En Remoto', 'Tamaño'])
        
        for path, info in sorted(resultados.items()):
            writer.writerow([
                path,
                info.status,
                '✓' if info.local_exists else '✗',
                '✓' if info.remote_exists else '✗',
                info.size
            ])
    
    print("✓ Reporte exportado a: reporte_comparacion.csv")
    
    # Exportar a JSON para procesamiento posterior
    import json
    from dataclasses import asdict
    
    datos_json = {
        'fecha': __import__('datetime').datetime.now().isoformat(),
        'archivos': [asdict(info) for info in resultados.values()],
        'estadisticas': {
            'total': len(resultados),
            'identicos': len([i for i in resultados.values() if i.status == 'idéntico']),
            'diferentes': len([i for i in resultados.values() if i.status == 'contenido diferente']),
            'solo_local': len([i for i in resultados.values() if i.status == 'falta en remoto']),
            'solo_remoto': len([i for i in resultados.values() if i.status == 'falta en local']),
        }
    }
    
    with open('reporte_comparacion.json', 'w', encoding='utf-8') as f:
        json.dump(datos_json, f, indent=2, ensure_ascii=False)
    
    print("✓ Reporte exportado a: reporte_comparacion.json")
    
    comparador.close()


def ejemplo_busqueda_selectiva():
    """Ejemplo: Buscar y comparar archivos específicos"""
    
    print("\n" + "=" * 70)
    print("EJEMPLO 6: Búsqueda selectiva por patrón")
    print("=" * 70)
    
    comparador = DirectoryComparator('~/local', '~/remoto')
    resultados = comparador.compare()
    
    # Buscar archivos con patrón
    patrones = ['.txt', '.md', 'README', 'config']
    
    for patron in patrones:
        archivos_coinciden = [
            (path, info) for path, info in resultados.items() 
            if patron.lower() in path.lower()
        ]
        
        if archivos_coinciden:
            print(f"\n📄 Archivos con '{patron}':")
            for path, info in archivos_coinciden:
                simbolo = '✓' if info.status == 'idéntico' else '⚠️'
                print(f"  {simbolo} {path} ({info.status})")
    
    comparador.close()


def ejemplo_estadisticas_avanzadas():
    """Ejemplo: Análisis estadístico detallado"""
    
    print("\n" + "=" * 70)
    print("EJEMPLO 7: Estadísticas avanzadas")
    print("=" * 70)
    
    comparador = DirectoryComparator('~/local', '~/remoto')
    resultados = comparador.compare()
    
    # Calcular estadísticas
    total_archivos = len(resultados)
    tamaño_total_local = sum(
        info.size for info in resultados.values() 
        if info.local_exists
    )
    tamaño_total_remoto = sum(
        info.size for info in resultados.values() 
        if info.remote_exists
    )
    
    # Archivos más grandes
    archivos_grandes = sorted(
        resultados.items(),
        key=lambda x: x[1].size,
        reverse=True
    )[:5]
    
    print(f"\n📊 Estadísticas:")
    print(f"  Total de archivos: {total_archivos}")
    print(f"  Tamaño total local: {tamaño_total_local / 1024 / 1024:.2f} MB")
    print(f"  Tamaño total remoto: {tamaño_total_remoto / 1024 / 1024:.2f} MB")
    
    print(f"\n📦 Top 5 archivos más grandes:")
    for path, info in archivos_grandes:
        tamaño_mb = info.size / 1024 / 1024
        print(f"  {path}: {tamaño_mb:.2f} MB")
    
    comparador.close()


if __name__ == '__main__':
    print("\n" + "🔍 COMPARADOR DE DIRECTORIOS - EJEMPLOS DE USO" + "\n")
    
    # Descomentar el ejemplo que quieras ejecutar:
    
    # ejemplo_comparacion_basica()
    # ejemplo_ver_diffs()
    # ejemplo_filtrado_selectivo()
    # ejemplo_con_ssh()
    # ejemplo_exportar_reporte()
    # ejemplo_busqueda_selectiva()
    # ejemplo_estadisticas_avanzadas()
    
    print("\n" + "=" * 70)
    print("Para ejecutar los ejemplos, descomentalos en el código")
    print("o ejecuta directamente desde CLI:")
    print("  python directory_comparator.py ~/carpeta1 ~/carpeta2")
    print("=" * 70 + "\n")
