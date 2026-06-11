#!/usr/bin/env python3
"""
Script para convertir PPK a OpenSSH usando pyasn1 + parser binario robusto
Version 3 - Con soporte mejorado para estructuras PPK complejas

Uso: python convertir_ppk_v3.py archivo.ppk
"""

import sys
import os
from pathlib import Path
import base64
import io
import struct
import hashlib
import subprocess


def try_ssh_keygen(archivo_ppk):
    """Intentar convertir con ssh-keygen (si está disponible)"""
    try:
        result = subprocess.run(
            ["ssh-keygen", "-i", "-f", str(archivo_ppk), "-m", "pem"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def parse_ppk_with_pyasn1(archivo_ppk):
    """Parser PPK robusto usando pyasn1"""
    try:
        from Crypto.PublicKey import RSA
        from pyasn1.codec.der import decoder
        from pyasn1.type import univ
    except ImportError as e:
        print(f"ERROR: Falta librería: {e}")
        return None

    try:
        with open(archivo_ppk, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        lines = content.split('\n')

        # Buscar Private-Lines
        private_lines_start = None
        private_lines_count = 0

        for i, line in enumerate(lines):
            if line.startswith('Private-Lines:'):
                private_lines_count = int(line.split(':')[1].strip())
                private_lines_start = i + 1
                break

        if private_lines_start is None:
            print("ERROR: No se encontró 'Private-Lines' en el archivo PPK")
            return None

        # Extraer líneas privadas
        private_lines = []
        for i in range(private_lines_start, private_lines_start + private_lines_count):
            if i < len(lines):
                private_lines.append(lines[i].strip())

        if not private_lines:
            print("ERROR: No se pudieron leer las líneas privadas")
            return None

        # Decodificar base64
        try:
            private_blob = base64.b64decode(''.join(private_lines))
            print(f"✓ Blob decodificado: {len(private_blob)} bytes")
        except Exception as e:
            print(f"ERROR decodificando base64: {e}")
            return None

        # Parsear estructura PPK (binaria)
        stream = io.BytesIO(private_blob)

        def read_mpint(s):
            """Lee un integer múltiple precisión (format PPK)"""
            length_bytes = s.read(2)
            if len(length_bytes) < 2:
                raise ValueError("No hay suficientes bytes para leer longitud")
            bit_length = int.from_bytes(length_bytes, 'big')
            byte_length = (bit_length + 7) // 8
            data = s.read(byte_length)
            if len(data) < byte_length:
                raise ValueError(f"No hay suficientes bytes: esperaba {byte_length}, recibió {len(data)}")
            return int.from_bytes(data, 'big')

        def read_string(s):
            """Lee una cadena (format PPK)"""
            length_bytes = s.read(4)
            if len(length_bytes) < 4:
                raise ValueError("No hay suficientes bytes para leer longitud de string")
            length = int.from_bytes(length_bytes, 'big')
            data = s.read(length)
            if len(data) < length:
                raise ValueError(f"String truncado: esperaba {length}, recibió {len(data)}")
            return data

        try:
            # Leer tipo de clave
            key_type_bytes = read_string(stream)
            key_type = key_type_bytes.decode('utf-8', errors='ignore')
            print(f"✓ Tipo de clave detectado: {key_type}")

            # Para RSA (ssh-rsa)
            if 'rsa' in key_type.lower():
                print("✓ Parseando como RSA...")

                try:
                    # En PPK, el orden para RSA es: n, e, d, p, q, u (iqmp)
                    n = read_mpint(stream)
                    e = read_mpint(stream)
                    d = read_mpint(stream)
                    p = read_mpint(stream)
                    q = read_mpint(stream)
                    u = read_mpint(stream)  # iqmp

                    print(f"  - n: {len(bin(n))} bits")
                    print(f"  - e: {e}")
                    print(f"  - d: privado")
                    print(f"  - p: privado")
                    print(f"  - q: privado")
                    print(f"  - u: privado")

                    # Crear clave RSA
                    rsa_key = RSA.construct((n, e, d, p, q, u), consistency_check=False)

                    # Exportar a OpenSSH
                    output_file = Path(archivo_ppk).parent / f"{Path(archivo_ppk).stem}_openssh"

                    with open(output_file, 'wb') as f:
                        key_data = rsa_key.exportKey(format='OpenSSH')
                        if isinstance(key_data, str):
                            f.write(key_data.encode('utf-8'))
                        else:
                            f.write(key_data)

                    os.chmod(output_file, 0o600)

                    print(f"\n✓ Exito - Convertido con pyasn1 (RSA)")
                    print(f"✓ Archivo: {output_file}")
                    return str(output_file)

                except Exception as e:
                    print(f"ERROR parseando RSA: {e}")
                    import traceback
                    traceback.print_exc()
                    return None

            elif 'ecdsa' in key_type.lower():
                print("⚠ ECDSA detectado pero no implementado aún")
                return None

            elif 'ed25519' in key_type.lower():
                print("⚠ Ed25519 detectado pero no implementado aún")
                return None

            else:
                print(f"⚠ Tipo de clave no soportado: {key_type}")
                return None

        except Exception as e:
            print(f"ERROR parseando estructura PPK: {e}")
            import traceback
            traceback.print_exc()
            return None

    except Exception as e:
        print(f"ERROR general: {e}")
        import traceback
        traceback.print_exc()
        return None


def convertir_ppk(archivo_ppk):
    """Intenta convertir PPK por varios métodos"""

    key_path = Path(archivo_ppk).expanduser()

    if not key_path.exists():
        print(f"ERROR: Archivo no encontrado: {archivo_ppk}")
        return False

    print("=" * 70)
    print("Convertidor PPK v3 (ssh-keygen + pyasn1 parser)")
    print("=" * 70)
    print()
    print(f"Leyendo: {key_path.name}")
    print()

    # Método 1: ssh-keygen
    print("1. Intentando con ssh-keygen...")
    resultado = try_ssh_keygen(str(key_path))
    if resultado:
        output_file = key_path.parent / f"{key_path.stem}_openssh"
        with open(output_file, 'w') as f:
            f.write(resultado)
        os.chmod(output_file, 0o600)
        print(f"   ✓ Exito con ssh-keygen")
        print(f"   ✓ Archivo: {output_file}")
        return True
    else:
        print("   ✗ ssh-keygen falló")

    # Método 2: pyasn1 parser
    print("\n2. Intentando con pyasn1 parser...")
    resultado = parse_ppk_with_pyasn1(str(key_path))
    if resultado:
        print(f"\n✓ EXITO - Archivo convertido:")
        print(f"\n   {resultado}")
        print(f"\n   Ahora usa esta ruta en el comparador:")
        print(f"   Ruta de Clave: {resultado}")
        return True
    else:
        print("   ✗ pyasn1 parser falló")

    # Si todo falla
    print("\n" + "=" * 70)
    print("SOLUCION")
    print("=" * 70)
    print("\nNo se puede convertir automaticamente con estos métodos.")
    print("\nOpciones:")
    print("\n1. RECOMENDADO - Convertir manualmente con PuTTYgen:")
    print("   - Abre PuTTYgen")
    print("   - Load -> dev26.rodavigo.ppk")
    print("   - Conversions -> Export OpenSSH key")
    print("   - Guarda como: dev26.rodavigo_openssh (SIN extension)")
    print("\n2. Instalar Git Bash (incluye ssh-keygen):")
    print("   https://git-scm.com/download/win")
    print("\n3. Contactar a Rodavigo para solicitar clave en OpenSSH format")

    return False


def main():
    if len(sys.argv) < 2:
        print("Uso: python convertir_ppk_v3.py archivo.ppk")
        print("\nEjemplo:")
        print("  python convertir_ppk_v3.py dev26.rodavigo.ppk")
        sys.exit(1)

    archivo = sys.argv[1]

    if convertir_ppk(archivo):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()