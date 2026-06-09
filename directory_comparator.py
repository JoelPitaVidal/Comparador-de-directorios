#!/usr/bin/env python3
"""
Comparador de directorios con interfaz web interactiva
Permite escribir rutas, seleccionar local/remoto y mantiene el servidor activo
"""

import os
import os
import json
import hashlib
import difflib
from pathlib import Path
from typing import Dict, Optional, Tuple
import argparse
from dataclasses import dataclass, asdict
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import socket
from datetime import datetime
import traceback

try:
    import paramiko

    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False

try:
    from cryptography.hazmat.primitives.asymmetric import rsa, dsa, ec, ed25519
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend

    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


@dataclass
class FileInfo:
    path: str
    size: int
    status: str
    local_exists: bool
    remote_exists: bool


class DirectoryComparator:
    def __init__(self, local_path: str, remote_path: str, ssh_config: Optional[Dict] = None):
        # Manejar la ruta de forma más flexible
        local_path = local_path.strip()

        # Detectar si es ruta de Windows
        is_windows_path = (
                (len(local_path) >= 2 and local_path[1] == ':') or  # C:
                local_path.startswith('\\\\')  # UNC path
        )

        self.remote_path = remote_path.strip()
        self.ssh_config = ssh_config
        self.sftp_client = None
        self.ssh_client = None
        self.is_remote = ssh_config is not None

        # LÓGICA CLAVE:
        # Si es ruta Windows + está marcado Remoto = NO validar localmente
        # (la validación ocurrirá cuando se ejecute en la máquina Windows del usuario)

        if is_windows_path and self.is_remote:
            # Confiar en que el usuario tiene la ruta correcta
            # Se validará cuando Python ejecute en su máquina Windows
            self.local_path = Path(local_path).expanduser()
        else:
            # Validación normal para rutas Linux
            test_path = Path(local_path).expanduser()

            if not test_path.exists():
                try:
                    test_path = test_path.resolve()
                except:
                    pass

            self.local_path = test_path

            # Validación solo para rutas Linux locales
            if not self.local_path.exists():
                error_msg = f"❌ Directorio local no existe\n\n"
                error_msg += f"Ruta proporcionada: {local_path}\n"
                error_msg += f"Ruta expandida: {self.local_path}\n\n"
                error_msg += f"💡 Verifica:\n"
                error_msg += f"  • ¿La ruta existe?\n"
                error_msg += f"  • ¿Tienes permisos de lectura?\n"
                error_msg += f"  • En Linux: usa rutas absolutas (Ej: /home/user/carpeta)\n"
                raise FileNotFoundError(error_msg)

        if self.is_remote and PARAMIKO_AVAILABLE:
            self._connect_ssh()

    def _connect_ssh(self):
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                'hostname': self.ssh_config['hostname'],
                'username': self.ssh_config.get('username', 'root'),
                'port': self.ssh_config.get('port', 22),
                'timeout': 10,
            }

            if 'password' in self.ssh_config and self.ssh_config['password']:
                connect_kwargs['password'] = self.ssh_config['password']
            elif 'key_file' in self.ssh_config and self.ssh_config['key_file']:
                key_file = self.ssh_config['key_file']

                # Convertir .ppk a OpenSSH si es necesario
                key_file = self._handle_ppk_key(key_file)

                connect_kwargs['key_filename'] = key_file

            self.ssh_client.connect(**connect_kwargs)
            self.sftp_client = self.ssh_client.open_sftp()
        except Exception as e:
            raise ConnectionError(f"Error SSH: {str(e)}")

    def _handle_ppk_key(self, key_file: str) -> str:
        key_path = Path(key_file).expanduser()

        if not key_path.exists():
            raise FileNotFoundError(f"Archivo de clave no existe: {key_file}")

        if not key_path.suffix.lower() == '.ppk':
            return str(key_path)

        import tempfile
        import subprocess

        # Metodo 1: Intentar con puttygen.exe (Windows)
        try:
            return self._convert_ppk_with_puttygen(key_path)
        except Exception as e:
            pass

        # Metodo 2: Intentar con ssh-keygen
        try:
            return self._convert_ppk_with_ssh_keygen(key_path)
        except Exception as e:
            pass

        # Metodo 3: Parser custom
        try:
            if CRYPTOGRAPHY_AVAILABLE:
                return self._convert_ppk_custom_parser(key_path)
        except Exception as e:
            pass

        raise ValueError(
            f"No se puede procesar el archivo PPK automaticamente.\n"
            f"El formato es demasiado complejo o no estándar.\n\n"
            f"Solucion: Convierte manualmente con PuTTYgen (2 minutos):\n"
            f"1. Abre PuTTYgen\n"
            f"2. Load -> {key_path.name}\n"
            f"3. Conversions -> Export OpenSSH key\n"
            f"4. Guarda el archivo sin extension .ppk\n"
            f"5. Usa la nueva ruta en el comparador\n\n"
            f"PuTTYgen es 100% confiable para cualquier formato PPK."
        )

    def _convert_ppk_with_puttygen(self, key_path: Path) -> str:
        import subprocess
        import tempfile

        temp_dir = Path(tempfile.gettempdir())
        output_file = temp_dir / f"{key_path.stem}_openssh_{os.getpid()}"

        puttygen_paths = [
            "puttygen.exe",
            "C:\\Program Files\\PuTTY\\puttygen.exe",
            "C:\\Program Files (x86)\\PuTTY\\puttygen.exe",
            str(Path.home() / "AppData" / "Local" / "Programs" / "PuTTY" / "puttygen.exe"),
        ]

        puttygen_exe = None
        for path in puttygen_paths:
            if Path(path).exists():
                puttygen_exe = path
                break

        if not puttygen_exe:
            try:
                result = subprocess.run(
                    ["where", "puttygen"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    puttygen_exe = result.stdout.strip().split('\n')[0]
            except:
                pass

        if not puttygen_exe:
            raise RuntimeError("puttygen.exe no encontrado")

        try:
            result = subprocess.run(
                [puttygen_exe, "-i", str(key_path), "-O", "private-openssh", "-o", str(output_file)],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0 and output_file.exists():
                output_file.chmod(0o600)
                return str(output_file)
            else:
                raise RuntimeError(f"puttygen fallo: {result.stderr}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("puttygen timeout")

    def _convert_ppk_with_ssh_keygen(self, key_path: Path) -> str:
        import subprocess
        import tempfile

        temp_dir = Path(tempfile.gettempdir())
        output_file = temp_dir / f"{key_path.stem}_openssh_{os.getpid()}"

        try:
            result = subprocess.run(
                ["ssh-keygen", "-i", "-f", str(key_path), "-m", "pem"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                with open(output_file, 'w') as f:
                    f.write(result.stdout)
                output_file.chmod(0o600)
                return str(output_file)
            else:
                raise RuntimeError(f"ssh-keygen fallo: {result.stderr}")
        except FileNotFoundError:
            raise RuntimeError("ssh-keygen no encontrado")
        except subprocess.TimeoutExpired:
            raise RuntimeError("ssh-keygen timeout")

    def _convert_ppk_custom_parser(self, key_path: Path) -> str:
        import io
        import base64
        import tempfile

        with open(key_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        lines = content.split('\n')
        public_blob, private_blob = self._extract_ppk_sections_from_lines(lines)

        if not private_blob:
            raise ValueError("No se encontro Private-Lines")

        stream = io.BytesIO(private_blob)
        key_data = self._parse_ppk_blob_robusto(stream)

        if key_data['type'] == 'rsa':
            openssh_bytes = self._generate_openssh_rsa(key_data)
        elif key_data['type'] == 'dsa':
            openssh_bytes = self._generate_openssh_dsa(key_data)
        elif key_data['type'] == 'ecdsa':
            openssh_bytes = self._generate_openssh_ecdsa(key_data)
        elif key_data['type'] == 'ed25519':
            openssh_bytes = self._generate_openssh_ed25519(key_data)
        else:
            raise ValueError(f"Tipo no soportado: {key_data['type']}")

        temp_dir = Path(tempfile.gettempdir())
        output_file = temp_dir / f"{key_path.stem}_openssh_{os.getpid()}"

        with open(output_file, 'wb') as f:
            f.write(openssh_bytes)

        output_file.chmod(0o600)
        return str(output_file)

    def _extract_ppk_sections_from_lines(self, lines) -> tuple:
        import base64

        public_blob = None
        private_blob = None

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if line.startswith('Public-Lines:'):
                try:
                    count = int(line.split(':')[1].strip())
                    i += 1
                    public_lines = []
                    for j in range(count):
                        if i < len(lines):
                            public_lines.append(lines[i].strip())
                            i += 1
                    public_blob = base64.b64decode(''.join(public_lines))
                    continue
                except:
                    i += 1
                    continue

            if line.startswith('Private-Lines:'):
                try:
                    count = int(line.split(':')[1].strip())
                    i += 1
                    private_lines = []
                    for j in range(count):
                        if i < len(lines):
                            private_lines.append(lines[i].strip())
                            i += 1
                    private_blob = base64.b64decode(''.join(private_lines))
                    continue
                except:
                    i += 1
                    continue

            i += 1

        return public_blob, private_blob

    def _extract_ppk_sections(self, key_path: Path) -> tuple:
        import base64

        with open(key_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        lines = content.split('\n')
        public_blob = None
        private_blob = None

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if line.startswith('Public-Lines:'):
                try:
                    count = int(line.split(':')[1].strip())
                    i += 1
                    public_lines = []
                    for j in range(count):
                        if i < len(lines):
                            public_lines.append(lines[i].strip())
                            i += 1
                        else:
                            break

                    blob_b64 = ''.join(public_lines)
                    public_blob = base64.b64decode(blob_b64)
                    continue
                except Exception:
                    i += 1
                    continue

            if line.startswith('Private-Lines:'):
                try:
                    count = int(line.split(':')[1].strip())
                    i += 1
                    private_lines = []
                    for j in range(count):
                        if i < len(lines):
                            private_lines.append(lines[i].strip())
                            i += 1
                        else:
                            break

                    blob_b64 = ''.join(private_lines)
                    private_blob = base64.b64decode(blob_b64)
                    continue
                except Exception:
                    i += 1
                    continue

            i += 1

        return public_blob, private_blob

    def _read_string_robusto(self, stream, max_len: int = 10000000) -> bytes:
        length_bytes = stream.read(4)
        if len(length_bytes) < 4:
            raise ValueError("No hay suficientes bytes para longitud")

        length = int.from_bytes(length_bytes, 'big')

        if length > max_len or length < 0:
            raise ValueError(f"Longitud invalida: {length}")

        data = stream.read(length)
        if len(data) < length:
            raise ValueError(f"Stream truncado: esperaba {length}, obtuvo {len(data)}")

        return data

    def _parse_ppk_blob_robusto(self, stream) -> dict:
        try:
            key_type = self._read_string_robusto(stream)

            if b'ssh-rsa' in key_type or b'rsa' in key_type.lower():
                return self._parse_ppk_rsa_key(stream)
            elif b'dss' in key_type.lower() or b'dsa' in key_type.lower():
                return self._parse_ppk_dsa_key(stream)
            elif b'ecdsa' in key_type.lower():
                return self._parse_ppk_ecdsa_key(stream)
            elif b'ed25519' in key_type.lower():
                return self._parse_ppk_ed25519_key(stream)
            else:
                stream.seek(0)
                return self._parse_ppk_rsa_key(stream)

        except Exception as e:
            raise ValueError(f"Error parseando blob PPK: {str(e)}")

    def _parse_ppk_rsa_key(self, stream) -> dict:
        try:
            key_type = self._read_string_robusto(stream)
            e = self._read_string_robusto(stream)
            d = self._read_string_robusto(stream)
            n = self._read_string_robusto(stream)
            p = self._read_string_robusto(stream)
            q = self._read_string_robusto(stream)

            return {
                'type': 'rsa',
                'e': int.from_bytes(e, 'big'),
                'd': int.from_bytes(d, 'big'),
                'n': int.from_bytes(n, 'big'),
                'p': int.from_bytes(p, 'big'),
                'q': int.from_bytes(q, 'big')
            }
        except Exception as e:
            raise ValueError(f"Error parseando RSA: {str(e)}")

    def _parse_ppk_dsa_key(self, stream) -> dict:
        try:
            key_type = self._read_string_robusto(stream)
            p = self._read_string_robusto(stream)
            q = self._read_string_robusto(stream)
            g = self._read_string_robusto(stream)
            y = self._read_string_robusto(stream)
            x = self._read_string_robusto(stream)

            return {
                'type': 'dsa',
                'p': int.from_bytes(p, 'big'),
                'q': int.from_bytes(q, 'big'),
                'g': int.from_bytes(g, 'big'),
                'y': int.from_bytes(y, 'big'),
                'x': int.from_bytes(x, 'big')
            }
        except Exception as e:
            raise ValueError(f"Error parseando DSA: {str(e)}")

    def _parse_ppk_ecdsa_key(self, stream) -> dict:
        try:
            key_type = self._read_string_robusto(stream)
            curve_name = self._read_string_robusto(stream)
            point_data = self._read_string_robusto(stream)
            d = self._read_string_robusto(stream)

            return {
                'type': 'ecdsa',
                'curve': curve_name.decode('utf-8', errors='ignore'),
                'point': point_data,
                'd': int.from_bytes(d, 'big')
            }
        except Exception as e:
            raise ValueError(f"Error parseando ECDSA: {str(e)}")

    def _parse_ppk_ed25519_key(self, stream) -> dict:
        try:
            key_type = self._read_string_robusto(stream)
            public = self._read_string_robusto(stream)
            private_seed = self._read_string_robusto(stream)

            if len(private_seed) >= 32:
                private_seed = private_seed[:32]

            return {
                'type': 'ed25519',
                'public': public,
                'private': private_seed
            }
        except Exception as e:
            raise ValueError(f"Error parseando Ed25519: {str(e)}")

    def _generate_openssh_rsa(self, key_data: dict) -> bytes:
        try:
            e = key_data['e']
            d = key_data['d']
            n = key_data['n']
            p = key_data['p']
            q = key_data['q']

            dmp1 = d % (p - 1)
            dmq1 = d % (q - 1)
            iqmp = pow(q, -1, p)

            public_numbers = rsa.RSAPublicNumbers(e, n)
            private_numbers = rsa.RSAPrivateNumbers(p, q, d, dmp1, dmq1, iqmp, public_numbers)
            private_key = private_numbers.private_key(default_backend())

            return private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.OpenSSH,
                encryption_algorithm=serialization.NoEncryption()
            )

        except Exception as e:
            raise ValueError(f"Error generando OpenSSH RSA: {str(e)}")

    def _generate_openssh_dsa(self, key_data: dict) -> bytes:
        try:
            parameter_numbers = dsa.DSAParameterNumbers(key_data['p'], key_data['q'], key_data['g'])
            public_numbers = dsa.DSAPublicNumbers(key_data['y'], parameter_numbers)
            private_numbers = dsa.DSAPrivateNumbers(key_data['x'], public_numbers)
            private_key = private_numbers.private_key(default_backend())

            return private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.OpenSSH,
                encryption_algorithm=serialization.NoEncryption()
            )
        except Exception as e:
            raise ValueError(f"Error generando OpenSSH DSA: {str(e)}")

    def _generate_openssh_ecdsa(self, key_data: dict) -> bytes:
        try:
            curve_name = key_data['curve']

            if b'256' in curve_name.encode() or b'nistp256' in curve_name.encode():
                curve = ec.SECP256R1()
            elif b'384' in curve_name.encode() or b'nistp384' in curve_name.encode():
                curve = ec.SECP384R1()
            elif b'521' in curve_name.encode() or b'nistp521' in curve_name.encode():
                curve = ec.SECP521R1()
            else:
                curve = ec.SECP256R1()

            private_key = ec.derive_private_key(key_data['d'], curve, default_backend())

            return private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.OpenSSH,
                encryption_algorithm=serialization.NoEncryption()
            )
        except Exception as e:
            raise ValueError(f"Error generando OpenSSH ECDSA: {str(e)}")

    def _generate_openssh_ed25519(self, key_data: dict) -> bytes:
        try:
            private_key = ed25519.Ed25519PrivateKey.from_private_bytes(key_data['private'])

            return private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.OpenSSH,
                encryption_algorithm=serialization.NoEncryption()
            )
        except Exception as e:
            raise ValueError(f"Error generando OpenSSH Ed25519: {str(e)}")

    def _get_local_files(self) -> Dict[str, FileInfo]:
        files = {}
        try:
            for file_path in self.local_path.rglob('*'):
                if file_path.is_file():
                    rel_path = file_path.relative_to(self.local_path).as_posix()
                    files[rel_path] = FileInfo(
                        path=rel_path,
                        size=file_path.stat().st_size,
                        status='comparando...',
                        local_exists=True,
                        remote_exists=False
                    )
        except Exception as e:
            raise Exception(f"Error leyendo local: {str(e)}")
        return files

    def _get_remote_files(self) -> Dict[str, FileInfo]:
        files = {}

        if self.is_remote and self.sftp_client:
            try:
                def walk_sftp(path, prefix=""):
                    try:
                        for item in self.sftp_client.listdir_attr(path):
                            if item.filename.startswith('.'):
                                continue

                            item_path = f"{path}/{item.filename}".replace('\\', '/')
                            rel_path = f"{prefix}{item.filename}".lstrip('/')

                            # Verificar si es directorio
                            try:
                                self.sftp_client.stat(item_path)
                                if item.filename.count('.') == 0:
                                    walk_sftp(item_path, f"{rel_path}/")
                                    continue
                            except:
                                pass

                            files[rel_path] = FileInfo(
                                path=rel_path,
                                size=item.st_size,
                                status='comparando...',
                                local_exists=False,
                                remote_exists=True
                            )
                    except Exception as e:
                        print(f"Error en walk_sftp: {e}")

                walk_sftp(self.remote_path)
            except Exception as e:
                raise Exception(f"Error leyendo remoto: {str(e)}")
        else:
            # Directorio local simulando remoto
            try:
                remote_base = Path(self.remote_path).expanduser()

                if not remote_base.exists():
                    raise FileNotFoundError(f"Directorio remoto no existe: {self.remote_path}")

                for file_path in remote_base.rglob('*'):
                    if file_path.is_file():
                        rel_path = file_path.relative_to(remote_base).as_posix()
                        files[rel_path] = FileInfo(
                            path=rel_path,
                            size=file_path.stat().st_size,
                            status='comparando...',
                            local_exists=False,
                            remote_exists=True
                        )
            except FileNotFoundError:
                raise
            except Exception as e:
                raise Exception(f"Error leyendo remoto: {str(e)}")

        return files

    def _get_file_hash(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except:
            return ""

    def _get_remote_file_hash(self, remote_file_path: str) -> str:
        if self.is_remote and self.sftp_client:
            try:
                with self.sftp_client.file(remote_file_path) as f:
                    sha256_hash = hashlib.sha256()
                    while True:
                        data = f.read(4096)
                        if not data:
                            break
                        sha256_hash.update(data)
                    return sha256_hash.hexdigest()
            except:
                return ""
        else:
            return self._get_file_hash(Path(remote_file_path))

    def _read_local_file(self, rel_path: str) -> str:
        try:
            file_path = self.local_path / rel_path
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            return f"[Error: {e}]"

    def _read_remote_file(self, rel_path: str) -> str:
        if self.is_remote and self.sftp_client:
            try:
                remote_file = f"{self.remote_path}/{rel_path}".replace('\\', '/')
                with self.sftp_client.file(remote_file) as f:
                    return f.read().decode('utf-8', errors='ignore')
            except Exception as e:
                return f"[Error: {e}]"
        else:
            try:
                file_path = Path(self.remote_path).expanduser() / rel_path
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except Exception as e:
                return f"[Error: {e}]"

    def compare(self) -> Dict[str, FileInfo]:
        local_files = self._get_local_files()
        remote_files = self._get_remote_files()

        all_files = {**local_files, **remote_files}

        for rel_path in all_files:
            local_exists = rel_path in local_files
            remote_exists = rel_path in remote_files

            all_files[rel_path].local_exists = local_exists
            all_files[rel_path].remote_exists = remote_exists

            if local_exists and remote_exists:
                local_file = self.local_path / rel_path
                remote_file = f"{self.remote_path}/{rel_path}".replace('\\', '/')

                local_hash = self._get_file_hash(local_file)
                remote_hash = self._get_remote_file_hash(remote_file)

                if local_hash == remote_hash:
                    all_files[rel_path].status = 'idéntico'
                else:
                    all_files[rel_path].status = 'contenido diferente'
            elif local_exists and not remote_exists:
                all_files[rel_path].status = 'falta en remoto'
            elif remote_exists and not local_exists:
                all_files[rel_path].status = 'falta en local'

        return all_files

    def get_diff(self, rel_path: str) -> str:
        """Formato unificado (deprecated, usa get_diff_side_by_side)"""
        local_content = self._read_local_file(rel_path).splitlines(keepends=True)
        remote_content = self._read_remote_file(rel_path).splitlines(keepends=True)

        diff = difflib.unified_diff(
            remote_content,
            local_content,
            fromfile=f"remoto: {rel_path}",
            tofile=f"local: {rel_path}",
            lineterm=''
        )

        return '\n'.join(diff)

    def get_diff_side_by_side(self, rel_path: str) -> Dict:
        """Genera diff lado a lado para mejor visualización"""
        local_content = self._read_local_file(rel_path).splitlines()
        remote_content = self._read_remote_file(rel_path).splitlines()

        # Usar SequenceMatcher para alineación
        matcher = difflib.SequenceMatcher(None, remote_content, local_content)
        opcodes = matcher.get_opcodes()

        side_by_side = []
        remote_line_num = 1
        local_line_num = 1

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == 'equal':
                # Lineas iguales
                for i in range(i2 - i1):
                    side_by_side.append({
                        'type': 'equal',
                        'remote_line': remote_line_num,
                        'remote_text': remote_content[i1 + i] if i1 + i < len(remote_content) else '',
                        'local_line': local_line_num,
                        'local_text': local_content[j1 + i] if j1 + i < len(local_content) else ''
                    })
                    remote_line_num += 1
                    local_line_num += 1

            elif tag == 'replace':
                # Lineas modificadas
                max_lines = max(i2 - i1, j2 - j1)
                for i in range(max_lines):
                    remote_text = remote_content[i1 + i] if i1 + i < i2 else ''
                    local_text = local_content[j1 + i] if j1 + i < j2 else ''

                    side_by_side.append({
                        'type': 'replace',
                        'remote_line': remote_line_num if i1 + i < i2 else None,
                        'remote_text': remote_text,
                        'local_line': local_line_num if j1 + i < j2 else None,
                        'local_text': local_text
                    })

                    if i1 + i < i2:
                        remote_line_num += 1
                    if j1 + i < j2:
                        local_line_num += 1

            elif tag == 'delete':
                # Lineas eliminadas (solo en remoto)
                for i in range(i1, i2):
                    side_by_side.append({
                        'type': 'delete',
                        'remote_line': remote_line_num,
                        'remote_text': remote_content[i],
                        'local_line': None,
                        'local_text': ''
                    })
                    remote_line_num += 1

            elif tag == 'insert':
                # Lineas insertadas (solo en local)
                for i in range(j1, j2):
                    side_by_side.append({
                        'type': 'insert',
                        'remote_line': None,
                        'remote_text': '',
                        'local_line': local_line_num,
                        'local_text': local_content[i]
                    })
                    local_line_num += 1

        return {
            'path': rel_path,
            'total_lines': max(len(remote_content), len(local_content)),
            'remote_lines': len(remote_content),
            'local_lines': len(local_content),
            'changes': side_by_side
        }

    def close(self):
        if self.sftp_client:
            try:
                self.sftp_client.close()
            except:
                pass
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except:
                pass


class ComparatorWebHandler(BaseHTTPRequestHandler):
    # Variables de clase compartidas
    current_comparator = None
    current_results = None
    current_info = {}

    def do_GET(self):
        parsed_path = urlparse(self.path)

        if parsed_path.path == '/':
            self.serve_home()
        elif parsed_path.path == '/api/results':
            self.serve_results()
        elif parsed_path.path.startswith('/api/diff/'):
            rel_path = parsed_path.path[10:]
            self.serve_diff(rel_path)
        else:
            self.send_error(404)

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')

        try:
            data = json.loads(body)

            if 'action' in data and data['action'] == 'compare':
                result = self.handle_compare(data)
                self.send_json_response(result)
            else:
                self.send_json_response({'error': 'Acción desconocida'}, 400)
        except Exception as e:
            self.send_json_response({'error': str(e)}, 400)

    def handle_compare(self, data):
        """Maneja la solicitud de comparación"""
        try:
            local_path = data.get('local_path', '').strip()
            remote_path = data.get('remote_path', '').strip()
            is_remote = data.get('is_remote', False)

            if not local_path or not remote_path:
                return {'error': 'Las rutas son requeridas'}

            # Cerrar comparador anterior si existe
            if self.__class__.current_comparator:
                self.__class__.current_comparator.close()

            ssh_config = None
            if is_remote:
                if not PARAMIKO_AVAILABLE:
                    return {'error': 'Paramiko no instalado. Instala con: pip install paramiko'}

                ssh_host = data.get('ssh_host', '').strip()
                ssh_user = data.get('ssh_user', '').strip()
                ssh_password = data.get('ssh_password', '').strip()
                ssh_key = data.get('ssh_key', '').strip()
                ssh_port = int(data.get('ssh_port', 22))

                if not ssh_host or not ssh_user:
                    return {'error': 'Host y usuario SSH son requeridos'}

                ssh_config = {
                    'hostname': ssh_host,
                    'username': ssh_user,
                    'port': ssh_port,
                }

                # Intentar autenticación en este orden:
                # 1. Contraseña (si la proporciona)
                # 2. Clave SSH (si la proporciona)
                # 3. Sin autenticación explícita (ssh-agent o clave por defecto en ~/.ssh/)

                if ssh_password:
                    ssh_config['password'] = ssh_password
                elif ssh_key:
                    ssh_config['key_file'] = ssh_key
                # Si no proporciona ni contraseña ni clave, paramiko intentará con ssh-agent

            # Crear comparador
            comparator = DirectoryComparator(local_path, remote_path, ssh_config)

            # Ejecutar comparación
            results = comparator.compare()

            # Guardar datos
            self.__class__.current_comparator = comparator
            self.__class__.current_results = results
            self.__class__.current_info = {
                'local_path': str(comparator.local_path),
                'remote_path': remote_path,
                'is_remote': is_remote,
                'timestamp': datetime.now().isoformat(),
                'total_files': len(results),
            }

            # Calcular estadísticas
            stats = {
                'total': len(results),
                'identical': len([i for i in results.values() if i.status == 'idéntico']),
                'different': len([i for i in results.values() if i.status == 'contenido diferente']),
                'missing_remote': len([i for i in results.values() if i.status == 'falta en remoto']),
                'missing_local': len([i for i in results.values() if i.status == 'falta en local']),
            }

            return {
                'success': True,
                'message': f'Comparación completada: {len(results)} archivos',
                'stats': stats
            }

        except Exception as e:
            return {'error': f'Error: {str(e)}', 'traceback': traceback.format_exc()}

    def serve_home(self):
        html = self.get_html()
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def serve_results(self):
        if not self.__class__.current_results:
            self.send_json_response({'error': 'Sin resultados disponibles'}, 400)
            return

        results = [asdict(f) for f in self.__class__.current_results.values()]
        results.sort(key=lambda x: (x['status'], x['path']))

        self.send_json_response({
            'info': self.__class__.current_info,
            'results': results
        })

    def serve_diff(self, rel_path: str):
        if not self.__class__.current_comparator:
            self.send_json_response({'error': 'Sin comparación activa'}, 400)
            return

        try:
            diff_data = self.__class__.current_comparator.get_diff_side_by_side(rel_path)
            self.send_json_response(diff_data)
        except Exception as e:
            self.send_json_response({'error': str(e)}, 400)

    def send_json_response(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def get_html(self):
        return """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Comparador de Directorios</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { 
            max-width: 1200px; 
            margin: 0 auto;
        }
        .card {
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            padding: 30px;
            margin-bottom: 20px;
        }
        h1 { 
            color: white;
            margin-bottom: 30px;
            font-size: 32px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        .form-section {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        .form-group {
            display: flex;
            flex-direction: column;
        }
        label {
            font-weight: 600;
            color: #333;
            margin-bottom: 8px;
            font-size: 14px;
        }
        input[type="text"], input[type="password"], select {
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 6px;
            font-size: 14px;
            transition: all 0.3s;
            font-family: inherit;
        }
        input[type="text"]:focus, input[type="password"]:focus, select:focus {
            outline: none;
            border-color: #e74c3c;
            box-shadow: 0 0 0 3px rgba(231, 76, 60, 0.1);
        }
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
        }
        .ssh-config {
            display: none;
            grid-column: 1 / -1;
            padding: 20px;
            background: #f5f5f5;
            border-radius: 6px;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
        }
        .ssh-config.visible {
            display: grid;
        }
        .ssh-config .form-group {
            margin: 0;
        }
        .button-group {
            display: flex;
            gap: 10px;
            grid-column: 1 / -1;
        }
        button {
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            font-size: 14px;
        }
        .btn-primary {
            background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
            color: white;
            flex: 1;
        }
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(231, 76, 60, 0.4);
        }
        .btn-primary:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .btn-reset {
            background: #f0f0f0;
            color: #333;
        }
        .btn-reset:hover {
            background: #e0e0e0;
        }
        .status {
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 20px;
            display: none;
        }
        .status.show {
            display: block;
        }
        .status.success {
            background: #e8f5e9;
            color: #2e7d32;
            border: 1px solid #4caf50;
        }
        .status.error {
            background: #ffebee;
            color: #c62828;
            border: 1px solid #f44336;
        }
        .status.loading {
            background: #ffe8e6;
            color: #c0392b;
            border: 1px solid #e74c3c;
        }
        .spinner {
            display: inline-block;
            width: 14px;
            height: 14px;
            border: 2px solid #e74c3c;
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 8px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
            color: white;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value {
            font-size: 28px;
            font-weight: bold;
        }
        .stat-label {
            font-size: 12px;
            opacity: 0.9;
            margin-top: 5px;
        }

        .filter-buttons {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .filter-btn {
            padding: 8px 16px;
            border: 2px solid #ddd;
            background: white;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.2s;
            font-weight: 500;
        }
        .filter-btn.active {
            background: #e74c3c;
            color: white;
            border-color: #e74c3c;
        }
        .filter-btn:hover {
            border-color: #e74c3c;
        }

        .file-list {
            display: grid;
            gap: 10px;
            max-height: 600px;
            overflow-y: auto;
        }
        .file-item {
            background: #f9f9f9;
            padding: 12px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
            border-left: 4px solid transparent;
        }
        .file-item:hover {
            background: #f0f0f0;
            border-left-color: #e74c3c;
        }
        .file-item.selected {
            background: #ffe8e6;
            border-left-color: #e74c3c;
        }
        .file-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .file-name {
            font-weight: 500;
            color: #333;
            word-break: break-all;
            flex: 1;
        }
        .file-status {
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
            white-space: nowrap;
            margin-left: 10px;
        }
        .status-idéntico { background: #e8f5e9; color: #2e7d32; }
        .status-contenido_diferente { background: #fff3cd; color: #856404; }
        .status-falta_en_remoto { background: #f8d7da; color: #721c24; }
        .status-falta_en_local { background: #d1ecf1; color: #0c5460; }

        .details {
            display: none;
        }
        .details.show {
            display: block;
        }
        .detail-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 1px solid #e0e0e0;
        }
        .detail-header h3 {
            color: #333;
        }
        .close-detail {
            background: #f0f0f0;
            color: #333;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
        }
        .close-detail:hover {
            background: #e0e0e0;
        }

        .diff-container {
            background: #f5f5f5;
            padding: 15px;
            border-radius: 6px;
            max-height: 700px;
            overflow: auto;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.5;
        }

        /* Vista lado a lado */
        .diff-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
        }

        .diff-table tbody tr {
            border-bottom: 1px solid #e0e0e0;
        }

        .diff-table tbody tr:hover {
            background: #f9f9f9;
        }

        .diff-table td {
            padding: 0;
            width: 50%;
            vertical-align: top;
        }

        .diff-line-num {
            background: #f0f0f0;
            color: #999;
            padding: 4px 8px;
            text-align: right;
            width: 40px;
            user-select: none;
            border-right: 1px solid #ddd;
            font-size: 11px;
            flex-shrink: 0;
        }

        .diff-line-content {
            padding: 4px 8px;
            white-space: pre-wrap;
            word-break: break-word;
            flex: 1;
            overflow-x: auto;
        }

        .diff-remote {
            border-left: 3px solid #ffcdd2;
            border-right: 1px solid #e0e0e0;
        }

        .diff-local {
            border-left: 3px solid #c8e6c9;
        }

        .diff-equal .diff-line-content {
            background: #fafafa;
            color: #333;
        }

        .diff-delete .diff-line-content {
            background: #ffebee;
            color: #c62828;
        }

        .diff-insert .diff-line-content {
            background: #e8f5e9;
            color: #2e7d32;
        }

        .diff-replace-remote {
            background: #ffe0b2 !important;
            color: #e65100 !important;
        }

        .diff-replace-local {
            background: #bbdefb !important;
            color: #0d47a1 !important;
        }

        .diff-header-row {
            background: #e3f2fd;
            font-weight: bold;
            padding: 10px;
            text-align: center;
            color: #0066cc;
            border-bottom: 2px solid #0066cc;
        }

        .diff-header-container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0;
            margin-bottom: 15px;
            border: 1px solid #0066cc;
            border-radius: 4px 4px 0 0;
            overflow: hidden;
        }

        .diff-column-header {
            padding: 12px;
            background: #e3f2fd;
            color: #0066cc;
            font-weight: bold;
            text-align: center;
            border-right: 1px solid #0066cc;
        }

        .diff-column-header:last-child {
            border-right: none;
        }

        .diff-stats {
            background: #f5f5f5;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 15px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            font-size: 12px;
        }

        .diff-stats-item {
            padding: 8px;
            background: white;
            border-radius: 4px;
            border-left: 3px solid #0066cc;
        }

        .diff-line {
            white-space: pre-wrap;
            word-break: break-all;
        }

        .diff-line.diff-add { background: #e8f5e9; color: #2e7d32; padding: 2px 4px; }
        .diff-line.diff-remove { background: #ffebee; color: #c62828; padding: 2px 4px; }
        .diff-line.diff-context { color: #666; }
        .diff-line.diff-header { color: #0066cc; font-weight: bold; }

        .empty-state {
            text-align: center;
            padding: 40px;
            color: #999;
        }
        .empty-state-icon {
            font-size: 48px;
            margin-bottom: 10px;
        }

        @media (max-width: 768px) {
            .form-section {
                grid-template-columns: 1fr;
            }
            .ssh-config {
                grid-template-columns: 1fr !important;
            }
            h1 { font-size: 24px; }
            .card { padding: 20px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 Comparador de Directorios</h1>

        <div class="card">
            <h2 style="color: #333; margin-bottom: 20px;">⚙️ Configuración</h2>

            <div class="form-section">
                <div class="form-group">
                    <label for="local_path">📁 Ruta Local</label>
                    <input type="text" id="local_path" placeholder="~/carpeta_local o /ruta/absoluta">
                </div>

                <div class="form-group">
                    <label for="remote_path">📁 Ruta Remota</label>
                    <input type="text" id="remote_path" placeholder="~/carpeta_remota o /ruta/absoluta">
                </div>

                <div class="form-group">
                    <label style="margin-bottom: 0;">Tipo de Comparación</label>
                    <div class="checkbox-group" style="margin-top: 12px;">
                        <input type="checkbox" id="is_remote">
                        <label for="is_remote" style="margin: 0; font-weight: normal;">Remoto (SSH/SFTP)</label>
                    </div>
                </div>
            </div>

            <!-- Configuración SSH -->
            <div id="ssh_config" class="ssh-config">
                <div style="grid-column: 1 / -1; background: white; padding: 12px; border-radius: 4px; border-left: 4px solid #e74c3c; margin-bottom: 10px; font-size: 13px; color: #555;">
                    💡 <strong>Opciones de autenticación:</strong> Proporciona contraseña, clave SSH, o déjalas vacías si usas ssh-agent o claves por defecto en ~/.ssh/
                </div>
                <div class="form-group">
                    <label for="ssh_host">🌐 Host SSH</label>
                    <input type="text" id="ssh_host" placeholder="servidor.com">
                </div>

                <div class="form-group">
                    <label for="ssh_user">👤 Usuario</label>
                    <input type="text" id="ssh_user" placeholder="usuario">
                </div>

                <div class="form-group">
                    <label for="ssh_port">🔌 Puerto</label>
                    <input type="text" id="ssh_port" placeholder="22" value="22">
                </div>

                <div class="form-group">
                    <label>🔐 Autenticación</label>
                    <select id="auth_method">
                        <option value="password">Contraseña</option>
                        <option value="key">Clave privada</option>
                    </select>
                </div>

                <div class="form-group" id="password_group">
                    <label for="ssh_password">🔑 Contraseña (opcional)</label>
                    <input type="password" id="ssh_password" placeholder="Dejar vacío si no la necesita">
                </div>

                <div class="form-group" id="key_group" style="display: none;">
                    <label for="ssh_key">🗝️ Ruta de Clave (opcional)</label>
                    <input type="text" id="ssh_key" placeholder="~/.ssh/id_rsa">
                </div>
            </div>

            <!-- Botones -->
            <div class="button-group">
                <button class="btn-primary" id="compare_btn" onclick="compareDirectories()">
                    🚀 Comparar Directorios
                </button>
                <button class="btn-reset" onclick="resetForm()">Limpiar</button>
            </div>

            <!-- Estado -->
            <div id="status" class="status"></div>
        </div>

        <!-- Resultados -->
        <div id="results_section" class="card" style="display: none;">
            <h2 style="color: #333; margin-bottom: 15px;">📊 Resultados</h2>

            <div id="stats" class="stats"></div>

            <div class="filter-buttons">
                <button class="filter-btn active" data-filter="all">Todos</button>
                <button class="filter-btn" data-filter="idéntico">✓ Idénticos</button>
                <button class="filter-btn" data-filter="contenido diferente">⚠️ Diferentes</button>
                <button class="filter-btn" data-filter="falta en remoto">❌ Falta remoto</button>
                <button class="filter-btn" data-filter="falta en local">❌ Falta local</button>
            </div>

            <div id="file_list" class="file-list"></div>
        </div>

        <!-- Detalles -->
        <div id="details_section" class="card details">
            <div class="detail-header">
                <h3 id="detail_title"></h3>
                <button class="close-detail" onclick="closeDetails()">✕ Cerrar</button>
            </div>
            <div id="detail_content"></div>
        </div>
    </div>

    <script>
        let allFiles = [];
        let currentFilter = 'all';
        let isComparing = false;

        // Event listeners
        document.getElementById('is_remote').addEventListener('change', (e) => {
            const sshConfig = document.getElementById('ssh_config');
            if (e.target.checked) {
                sshConfig.classList.add('visible');
            } else {
                sshConfig.classList.remove('visible');
            }
        });

        document.getElementById('auth_method').addEventListener('change', (e) => {
            const passwordGroup = document.getElementById('password_group');
            const keyGroup = document.getElementById('key_group');
            if (e.target.value === 'password') {
                passwordGroup.style.display = 'flex';
                keyGroup.style.display = 'none';
            } else {
                passwordGroup.style.display = 'none';
                keyGroup.style.display = 'flex';
            }
        });

        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                currentFilter = e.target.dataset.filter;
                renderResults();
            });
        });

        function showStatus(message, type) {
            const statusDiv = document.getElementById('status');
            statusDiv.className = `status show ${type}`;

            if (type === 'loading') {
                statusDiv.innerHTML = `<span class="spinner"></span>${message}`;
            } else {
                statusDiv.textContent = message;
            }
        }

        function compareDirectories() {
            if (isComparing) return;

            const localPath = document.getElementById('local_path').value.trim();
            const remotePath = document.getElementById('remote_path').value.trim();
            const isRemote = document.getElementById('is_remote').checked;

            if (!localPath || !remotePath) {
                showStatus('❌ Completa todas las rutas', 'error');
                return;
            }

            isComparing = true;
            document.getElementById('compare_btn').disabled = true;
            showStatus('Comparando directorios...', 'loading');

            const data = {
                action: 'compare',
                local_path: localPath,
                remote_path: remotePath,
                is_remote: isRemote,
            };

            if (isRemote) {
                const sshHost = document.getElementById('ssh_host').value.trim();
                const sshUser = document.getElementById('ssh_user').value.trim();
                const sshPort = document.getElementById('ssh_port').value.trim();
                const authMethod = document.getElementById('auth_method').value;

                if (!sshHost || !sshUser) {
                    showStatus('❌ Host y usuario SSH son requeridos', 'error');
                    isComparing = false;
                    document.getElementById('compare_btn').disabled = false;
                    return;
                }

                data.ssh_host = sshHost;
                data.ssh_user = sshUser;
                data.ssh_port = sshPort;

                if (authMethod === 'password') {
                    data.ssh_password = document.getElementById('ssh_password').value;
                } else {
                    data.ssh_key = document.getElementById('ssh_key').value;
                }
            }

            fetch('/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            })
            .then(r => r.json())
            .then(result => {
                if (result.error) {
                    showStatus(`❌ ${result.error}`, 'error');
                } else {
                    showStatus(`✅ ${result.message}`, 'success');
                    loadResults();
                }
            })
            .catch(e => {
                showStatus(`❌ Error: ${e.message}`, 'error');
            })
            .finally(() => {
                isComparing = false;
                document.getElementById('compare_btn').disabled = false;
            });
        }

        function loadResults() {
            fetch('/api/results')
                .then(r => r.json())
                .then(data => {
                    allFiles = data.results;
                    renderStats(data.info);
                    renderResults();
                    document.getElementById('results_section').style.display = 'block';
                });
        }

        function renderStats(info) {
            const stats = {
                total: info.total_files,
                identical: 0,
                different: 0,
                missing: 0
            };

            allFiles.forEach(f => {
                if (f.status === 'idéntico') stats.identical++;
                else if (f.status === 'contenido diferente') stats.different++;
                else stats.missing++;
            });

            document.getElementById('stats').innerHTML = `
                <div class="stat-card">
                    <div class="stat-value">${stats.total}</div>
                    <div class="stat-label">Total</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.identical}</div>
                    <div class="stat-label">Idénticos</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.different}</div>
                    <div class="stat-label">Diferentes</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.missing}</div>
                    <div class="stat-label">Faltantes</div>
                </div>
            `;
        }

        function renderResults() {
            const filtered = currentFilter === 'all' 
                ? allFiles 
                : allFiles.filter(f => f.status === currentFilter);

            if (filtered.length === 0) {
                document.getElementById('file_list').innerHTML = 
                    '<div class="empty-state"><div class="empty-state-icon">📭</div><p>Sin archivos en esta categoría</p></div>';
                return;
            }

            let html = '';
            filtered.forEach((file, idx) => {
                const statusClass = 'status-' + file.status.replace(/ /g, '_');
                html += `
                    <div class="file-item" onclick="showDetails('${escapeJs(file.path)}')">
                        <div class="file-header">
                            <div class="file-name">📄 ${escapeHtml(file.path)}</div>
                            <div class="file-status ${statusClass}">${file.status}</div>
                        </div>
                    </div>
                `;
            });
            document.getElementById('file_list').innerHTML = html;
        }

        function showDetails(path) {
            document.getElementById('detail_title').textContent = path;
            document.getElementById('detail_content').innerHTML = '<div class="loading"><span class="spinner"></span> Cargando...</div>';
            document.getElementById('details_section').classList.add('show');

            const file = allFiles.find(f => f.path === path);

            if (file.status === 'contenido diferente') {
                fetch(`/api/diff/${encodeURIComponent(path)}`)
                    .then(r => r.json())
                    .then(diffData => {
                        // Generar HTML lado a lado
                        let html = '<div class="diff-container">';

                        // Encabezado con estadísticas
                        html += `
                            <div class="diff-stats">
                                <div class="diff-stats-item">
                                    <strong>Remoto:</strong> ${diffData.remote_lines} líneas
                                </div>
                                <div class="diff-stats-item">
                                    <strong>Local:</strong> ${diffData.local_lines} líneas
                                </div>
                            </div>
                        `;

                        // Headers de columnas
                        html += `
                            <div class="diff-header-container">
                                <div class="diff-column-header remote">📋 Remoto</div>
                                <div class="diff-column-header local">📝 Local</div>
                            </div>
                        `;

                        // Tabla de diff
                        html += '<table class="diff-table">';

                        diffData.changes.forEach(change => {
                            const rowClass = change.type === 'equal' ? 'diff-equal' : 
                                           change.type === 'delete' ? 'diff-delete' :
                                           change.type === 'insert' ? 'diff-insert' : 'diff-replace';

                            const remoteClass = change.type === 'replace' ? 'diff-replace-remote' : '';
                            const localClass = change.type === 'replace' ? 'diff-replace-local' : '';

                            html += `<tr class="diff-row ${rowClass}">`;

                            // Columna remoto
                            html += '<td class="diff-remote">';
                            if (change.remote_line) {
                                html += `<div style="display: flex;"><div class="diff-line-num">${change.remote_line}</div><div class="diff-line-content ${remoteClass}">${escapeHtml(change.remote_text)}</div></div>`;
                            } else {
                                html += '<div style="display: flex;"><div class="diff-line-num"></div><div class="diff-line-content" style="background: #f5f5f5;"></div></div>';
                            }
                            html += '</td>';

                            // Columna local
                            html += '<td class="diff-local">';
                            if (change.local_line) {
                                html += `<div style="display: flex;"><div class="diff-line-num">${change.local_line}</div><div class="diff-line-content ${localClass}">${escapeHtml(change.local_text)}</div></div>`;
                            } else {
                                html += '<div style="display: flex;"><div class="diff-line-num"></div><div class="diff-line-content" style="background: #f5f5f5;"></div></div>';
                            }
                            html += '</td>';

                            html += '</tr>';
                        });

                        html += '</table>';
                        html += '</div>';

                        document.getElementById('detail_content').innerHTML = html;
                    })
                    .catch(e => {
                        document.getElementById('detail_content').innerHTML = `
                            <div style="color: #c62828; padding: 20px;">
                                <strong>Error al cargar diff:</strong> ${escapeHtml(e.message)}
                            </div>
                        `;
                    });
            } else {
                let info = '<p><strong>Estado:</strong> ' + file.status + '</p>';
                if (file.local_exists) info += '<p>✓ Existe en local</p>';
                if (file.remote_exists) info += '<p>✓ Existe en remoto</p>';
                if (!file.local_exists) info += '<p style="color: #c62828;">✗ Falta en local</p>';
                if (!file.remote_exists) info += '<p style="color: #c62828;">✗ Falta en remoto</p>';
                info += `<p style="color: #999; font-size: 12px; margin-top: 10px;">Tamaño: ${(file.size / 1024).toFixed(2)} KB</p>`;
                document.getElementById('detail_content').innerHTML = info;
            }
        }

        function closeDetails() {
            document.getElementById('details_section').classList.remove('show');
        }

        function resetForm() {
            document.getElementById('local_path').value = '';
            document.getElementById('remote_path').value = '';
            document.getElementById('is_remote').checked = false;
            document.getElementById('ssh_config').classList.remove('visible');
            document.getElementById('status').classList.remove('show');
            document.getElementById('results_section').style.display = 'none';
            document.getElementById('details_section').classList.remove('show');
            allFiles = [];
            currentFilter = 'all';
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function escapeJs(text) {
            return text.replace(/'/g, "\\'").replace(/"/g, '\\"');
        }
    </script>
</body>
</html>
        """

    def log_message(self, format, *args):
        pass


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def main():
    parser = argparse.ArgumentParser(
        description='Comparador web de directorios local/remoto'
    )
    parser.add_argument('--port', type=int, default=0, help='Puerto (default: automático)')
    parser.add_argument('--host', default='127.0.0.1', help='Host (default: 127.0.0.1)')

    args = parser.parse_args()

    try:
        port = args.port if args.port > 0 else find_free_port()
        server = HTTPServer((args.host, port), ComparatorWebHandler)

        print(f"\n{'=' * 70}")
        print(f"🌐 Comparador de Directorios Web")
        print(f"{'=' * 70}")
        print(f"\n✓ Servidor activo en: http://{args.host}:{port}")
        print(f"\n💡 Abre esta URL en tu navegador")
        print(f"📌 El servidor se mantiene activo - puedes hacer múltiples comparaciones")
        print(f"\n⌨️  Presiona Ctrl+C para detener\n")

        import webbrowser
        import time
        time.sleep(1)
        webbrowser.open(f'http://{args.host}:{port}')

        server.serve_forever()

    except KeyboardInterrupt:
        print("\n\n✓ Servidor detenido")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == '__main__':
    main()