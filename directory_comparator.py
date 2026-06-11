import os
import json
import hashlib
import difflib
import re
from pathlib import Path
from typing import Dict, Optional
import argparse
from dataclasses import dataclass, asdict
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import socket
from datetime import datetime
import traceback


# ============================================================================
# FUNCIONES DE PERSISTENCIA - MÚLTIPLES CONFIGURACIONES
# ============================================================================

def get_config_file():
    config_dir = Path.home() / '.comparador_directorios'
    config_dir.mkdir(exist_ok=True, parents=True)
    return config_dir / 'ssh_configs.json'


def load_all_ssh_configs():
    """Carga todas las configuraciones SSH guardadas"""
    config_file = get_config_file()
    default_structure = {
        'configurations': [],
        'last_used': None
    }

    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data
        except:
            return default_structure
    return default_structure


def save_ssh_config(config_name, config):
    """Guarda o actualiza una configuración SSH"""
    config_file = get_config_file()
    try:
        data = load_all_ssh_configs()

        # Buscar si la configuración ya existe
        existing = next((i for i, c in enumerate(data['configurations']) if c['name'] == config_name), None)

        new_config = {
            'name': config_name,
            'hostname': config.get('hostname', ''),
            'username': config.get('username', ''),
            'port': config.get('port', 22),
            'key_file': config.get('key_file', ''),
            'password': config.get('password', ''),
            'auth_type': config.get('auth_type', 'key'),
        }

        if existing is not None:
            data['configurations'][existing] = new_config
        else:
            data['configurations'].append(new_config)

        data['last_used'] = config_name

        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error guardando config: {e}")
        return False


def delete_ssh_config(config_name):
    """Borra una configuración SSH"""
    config_file = get_config_file()
    try:
        data = load_all_ssh_configs()
        data['configurations'] = [c for c in data['configurations'] if c['name'] != config_name]

        if data['last_used'] == config_name:
            data['last_used'] = data['configurations'][0]['name'] if data['configurations'] else None

        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except:
        return False


def clear_all_ssh_configs():
    """Limpia todas las configuraciones SSH"""
    config_file = get_config_file()
    try:
        if config_file.exists():
            config_file.unlink()
        return True
    except:
        return False


try:
    import paramiko

    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False


@dataclass
class FileInfo:
    path: str
    size: int
    status: str
    local_exists: bool
    remote_exists: bool


class DirectoryComparator:
    def __init__(self, local_path: str, remote_path: str, ssh_config: Optional[Dict] = None):
        local_path = local_path.strip()

        is_windows_path = (
                (len(local_path) >= 2 and local_path[1] == ':') or
                local_path.startswith('\\\\')
        )

        self.remote_path = remote_path.strip()
        self.ssh_config = ssh_config
        self.sftp_client = None
        self.ssh_client = None
        self.is_remote = ssh_config is not None

        if is_windows_path and self.is_remote:
            self.local_path = Path(local_path).expanduser()
        else:
            test_path = Path(local_path).expanduser()

            if not test_path.exists():
                try:
                    test_path = test_path.resolve()
                except:
                    pass

            self.local_path = test_path

            if not self.local_path.exists():
                raise FileNotFoundError(f"Directorio local no existe: {local_path}")

        if self.is_remote and PARAMIKO_AVAILABLE:
            self._connect_ssh()

    def _connect_ssh(self):
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                'hostname': self.ssh_config.get('hostname'),
                'username': self.ssh_config.get('username', 'root'),
                'port': int(self.ssh_config.get('port', 22)),
                'timeout': 10,
            }

            if self.ssh_config.get('password'):
                connect_kwargs['password'] = self.ssh_config['password']
            elif self.ssh_config.get('key_file'):
                key_path = Path(self.ssh_config['key_file']).expanduser()
                if not key_path.exists():
                    raise FileNotFoundError(f"Clave no existe: {self.ssh_config['key_file']}")
                connect_kwargs['key_filename'] = str(key_path)

            self.ssh_client.connect(**connect_kwargs)
            self.sftp_client = self.ssh_client.open_sftp()
        except Exception as e:
            raise ConnectionError(f"Error SSH: {str(e)}")

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
                    except:
                        pass

                walk_sftp(self.remote_path)
            except Exception as e:
                raise Exception(f"Error leyendo remoto: {str(e)}")
        else:
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

    def _extract_php_keys(self, content_str: str) -> list:
        """Extrae las claves/etiquetas de un archivo que retorna un array asociativo en PHP"""
        pattern = r"['\"]([^'\"]+)['\"]\s*=>"
        return re.findall(pattern, content_str)

    def _extract_single_line_key(self, line_text: str) -> Optional[str]:
        """Extrae la clave de una única línea PHP tipo 'key' => 'value'"""
        txt = line_text.strip()
        if '=>' not in txt:
            return None
        key_part = txt.split('=>')[0].strip()
        return key_part.replace("'", "").replace('"', "")

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

    def get_diff_side_by_side(self, rel_path: str) -> Dict:
        local_raw = self._read_local_file(rel_path)
        remote_raw = self._read_remote_file(rel_path)

        local_content = local_raw.splitlines()
        remote_content = remote_raw.splitlines()

        # ---------------------------------------------------------------------
        # ANÁLISIS INCISIVO DE ETIQUETAS
        # ---------------------------------------------------------------------
        is_php = rel_path.endswith('.php')
        tags_match_msg = ""

        if is_php:
            local_keys = self._extract_php_keys(local_raw)
            remote_keys = self._extract_php_keys(remote_raw)

            if local_keys == remote_keys:
                tags_match_msg = " [ESTRUCTURA DE ETIQUETAS IDÉNTICA]"
            else:
                missing_in_local = set(remote_keys) - set(local_keys)
                missing_in_remote = set(local_keys) - set(remote_keys)
                error_details = []
                if missing_in_local:
                    error_details.append(f"Faltan en Ruta 1: {list(missing_in_local)}")
                if missing_in_remote:
                    error_details.append(f"Faltan en Ruta 2: {list(missing_in_remote)}")

                if len(local_keys) == len(remote_keys):
                    tags_match_msg = " [⚠ ALERTA: Mismo número de elementos pero LAS ETIQUETAS DIFIEREN o están desordenadas]"
                else:
                    tags_match_msg = f" [❌ ERROR DE ETIQUETAS: {', '.join(error_details)}]"
        # ---------------------------------------------------------------------

        matcher = difflib.SequenceMatcher(None, remote_content, local_content)
        opcodes = matcher.get_opcodes()

        side_by_side = []
        remote_line_num = 1
        local_line_num = 1

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == 'equal':
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
                max_lines = max(i2 - i1, j2 - j1)
                for i in range(max_lines):
                    remote_text = remote_content[i1 + i] if i1 + i < i2 else ''
                    local_text = local_content[j1 + i] if j1 + i < j2 else ''

                    line_row_type = 'replace'
                    if is_php and remote_text and local_text:
                        rem_key = self._extract_single_line_key(remote_text)
                        loc_key = self._extract_single_line_key(local_text)

                        if rem_key and loc_key and rem_key == loc_key:
                            line_row_type = 'replace-only-value'

                    side_by_side.append({
                        'type': line_row_type,
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
            'path': rel_path + tags_match_msg,
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
            data = json.loads(body) if body else {}

            if self.path == '/api/save_config':
                config_name = data.get('config_name', '').strip()
                if not config_name:
                    self.send_json_response({'error': 'Nombre de configuración requerido'}, 400)
                    return

                config = {
                    'hostname': data.get('hostname', ''),
                    'username': data.get('username', ''),
                    'port': int(data.get('port', 22)),
                    'key_file': data.get('key_file', ''),
                    'password': data.get('password', ''),
                    'auth_type': data.get('auth_type', 'key'),
                }
                if save_ssh_config(config_name, config):
                    self.send_json_response({'status': 'saved', 'config_name': config_name})
                else:
                    self.send_json_response({'error': 'No se pudo guardar'}, 500)

            elif self.path == '/api/delete_config':
                config_name = data.get('config_name', '').strip()
                if delete_ssh_config(config_name):
                    self.send_json_response({'status': 'deleted'})
                else:
                    self.send_json_response({'error': 'No se pudo borrar'}, 500)

            elif self.path == '/api/load_all_configs':
                all_configs = load_all_ssh_configs()
                self.send_json_response(all_configs)

            elif self.path == '/api/clear_all_configs':
                if clear_all_ssh_configs():
                    self.send_json_response({'status': 'cleared'})
                else:
                    self.send_json_response({'error': 'No se pudo limpiar'}, 500)

            elif 'action' in data and data['action'] == 'compare':
                result = self.handle_compare(data)
                self.send_json_response(result)
            else:
                self.send_json_response({'error': 'Acción desconocida'}, 400)
        except Exception as e:
            self.send_json_response({'error': str(e)}, 400)

    def handle_compare(self, data):
        try:
            local_path = data.get('local_path', '').strip()
            remote_path = data.get('remote_path', '').strip()
            is_remote = data.get('is_remote', False)

            if not local_path or not remote_path:
                return {'error': 'Las rutas son requeridas'}

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

                if ssh_password:
                    ssh_config['password'] = ssh_password
                elif ssh_key:
                    ssh_config['key_file'] = ssh_key

            comparator = DirectoryComparator(local_path, remote_path, ssh_config)
            results = comparator.compare()

            self.__class__.current_comparator = comparator
            self.__class__.current_results = results
            self.__class__.current_info = {
                'local_path': str(comparator.local_path),
                'remote_path': remote_path,
                'is_remote': is_remote,
                'timestamp': datetime.now().isoformat(),
                'total_files': len(results),
            }

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
            return {'error': f'Error: {str(e)}'}

    def serve_home(self):
        all_configs = load_all_ssh_configs()
        html = self.get_html(all_configs)
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
            from urllib.parse import unquote
            rel_path = unquote(rel_path)
            diff_data = self.__class__.current_comparator.get_diff_side_by_side(rel_path)
            self.send_json_response(diff_data)
        except Exception as e:
            self.send_json_response({'error': str(e)}, 400)

    def send_json_response(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def get_html(self, all_configs):
        configs_json = json.dumps(all_configs, ensure_ascii=False)

        return f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Comparador de Directorios v4.2</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        .card {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            padding: 30px;
            margin-bottom: 20px;
        }}
        h1 {{ color: white; margin-bottom: 10px; font-size: 32px; text-shadow: 0 2px 4px rgba(0,0,0,0.2); }}
        .subtitle {{ color: rgba(255,255,255,0.8); font-size: 14px; margin-bottom: 30px; }}
        h2 {{ color: #333; margin-bottom: 20px; font-size: 18px; }}
        .section-title {{ color: #e74c3c; font-weight: bold; padding: 10px; background: #f5f5f5; border-left: 4px solid #e74c3c; margin-bottom: 15px; }}
        .form-section {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
        .form-group {{ display: flex; flex-direction: column; }}
        label {{ font-weight: 600; color: #333; margin-bottom: 8px; font-size: 14px; }}
        input, select {{ padding: 12px; border: 2px solid #e0e0e0; border-radius: 6px; font-size: 14px; font-family: monospace; }}
        input:focus, select:focus {{ outline: none; border-color: #e74c3c; box-shadow: 0 0 0 3px rgba(231, 76, 60, 0.1); }}
        .button-group {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 20px; }}
        button {{ padding: 12px 20px; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 14px; transition: all 0.3s; }}
        .btn-primary {{ background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%); color: white; flex: 1; min-width: 150px; }}
        .btn-primary:hover {{ transform: translateY(-2px); box-shadow: 0 5px 20px rgba(231, 76, 60, 0.4); }}
        .btn-secondary {{ background: #3498db; color: white; }}
        .btn-secondary:hover {{ background: #2980b9; }}
        .btn-success {{ background: #27ae60; color: white; }}
        .btn-success:hover {{ background: #229954; }}
        .btn-danger {{ background: #95a5a6; color: white; }}
        .btn-danger:hover {{ background: #7f8c8d; }}
        .btn-small {{ padding: 8px 12px; font-size: 12px; min-width: auto; }}
        .status {{ padding: 12px; border-radius: 6px; margin-top: 15px; display: none; }}
        .status.show {{ display: block; }}
        .status.success {{ background: #d5f4e6; color: #27ae60; border: 1px solid #27ae60; }}
        .status.error {{ background: #fadbd8; color: #c0392b; border: 1px solid #c0392b; }}
        .status.loading {{ background: #ffe8e6; color: #c0392b; }}
        .info-box {{ background: #e3f2fd; border-left: 4px solid #2196f3; padding: 12px; margin: 15px 0; border-radius: 4px; font-size: 13px; color: #1565c0; }}
        .config-selector {{ background: #f9f9f9; padding: 15px; border-radius: 6px; margin-bottom: 15px; }}
        .config-row {{ display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center; margin-bottom: 10px; }}
        .config-name {{ font-weight: 500; color: #333; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin: 20px 0; }}
        .stat-card {{ background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 28px; font-weight: bold; }}
        .stat-label {{ font-size: 12px; opacity: 0.9; margin-top: 5px; }}
        .file-item {{ background: #f9f9f9; padding: 12px; border-radius: 6px; margin: 8px 0; border-left: 4px solid transparent; }}
        .file-item:hover {{ background: #f0f0f0; border-left-color: #e74c3c; }}
        .file-header {{ display: flex; justify-content: space-between; align-items: center; }}
        .file-name {{ font-weight: 500; color: #333; word-break: break-all; flex: 1; }}
        .file-status {{ padding: 4px 8px; border-radius: 3px; font-size: 11px; font-weight: 600; white-space: nowrap; margin-left: 10px; }}
        .status-idéntico {{ background: #e8f5e9; color: #2e7d32; }}
        .status-contenido_diferente {{ background: #fff3cd; color: #856404; }}
        .status-falta_en_remoto {{ background: #f8d7da; color: #721c24; }}
        .status-falta_en_local {{ background: #d1ecf1; color: #0c5460; }}
        .filter-buttons {{ display: flex; gap: 10px; margin: 15px 0; flex-wrap: wrap; }}
        .filter-btn {{ padding: 8px 16px; border: 2px solid #ddd; background: white; border-radius: 4px; cursor: pointer; font-weight: 500; }}
        .filter-btn.active {{ background: #e74c3c; color: white; border-color: #e74c3c; }}
        .file-item.clickable {{ cursor: pointer; }}
        .file-item.clickable:hover .file-name {{ color: #e74c3c; text-decoration: underline; }}
        .diff-viewer {{ margin-top: 10px; display: none; border: 1px solid #ddd; border-radius: 6px; overflow: hidden; }}
        .diff-viewer.open {{ display: block; }}
        .diff-header {{ background: #333; color: white; padding: 8px 14px; font-size: 12px; display: flex; justify-content: space-between; align-items: center; }}
        .diff-header .diff-title {{ font-family: monospace; }}
        .diff-header .diff-close {{ cursor: pointer; color: #aaa; font-size: 16px; line-height: 1; }}
        .diff-header .diff-close:hover {{ color: white; }}
        .diff-cols {{ display: grid; grid-template-columns: 1fr 1fr; font-family: monospace; font-size: 12px; overflow-x: auto; }}
        .diff-col-header {{ background: #555; color: #ccc; padding: 6px 10px; font-size: 11px; font-weight: bold; text-align: center; }}
        .diff-table {{ width: 100%; border-collapse: collapse; }}
        .diff-table td {{ padding: 1px 8px; white-space: pre; vertical-align: top; }}
        .diff-table .ln {{ color: #999; text-align: right; min-width: 36px; user-select: none; border-right: 1px solid #ddd; padding-right: 6px; }}
        .diff-row-equal td {{ background: #fff; color: #333; }}
        .diff-row-replace td {{ background: #fff3cd; color: #856404; font-weight: bold; }}
        .diff-row-replace-only-value td {{ background: #e3f2fd; color: #1565c0; }}
        .diff-row-delete td {{ background: #ffeef0; color: #c0392b; }}
        .diff-row-insert td {{ background: #e8f5e9; color: #27ae60; }}
        .diff-row-empty td {{ background: #f5f5f5; color: #ccc; }}
        .diff-loading {{ padding: 20px; text-align: center; color: #999; font-size: 13px; }}
        @media (max-width: 768px) {{ .form-section {{ grid-template-columns: 1fr; }} h1 {{ font-size: 24px; }} .card {{ padding: 20px; }} .config-row {{ grid-template-columns: 1fr; }} .diff-cols {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Comparador de Directorios</h1>

        <div class="card">
            <div class="section-title">GESTIÓN DE CONFIGURACIONES SSH</div>

            <div class="config-selector">
                <div style="margin-bottom: 15px;">
                    <h3 style="font-size: 14px; color: #333; margin-bottom: 10px;">Configuraciones Guardadas:</h3>
                    <div id="saved_configs_list"></div>
                </div>

                <div style="border-top: 1px solid #ddd; padding-top: 15px; margin-top: 15px;">
                    <h3 style="font-size: 14px; color: #333; margin-bottom: 10px;"> Crear/Editar Configuración:</h3>

                    <div class="form-section">
                        <div class="form-group">
                            <label for="config_name">Nombre de Configuración *</label>
                            <input type="text" id="config_name" placeholder="Ej: Rodavigo, Admin Local, Producción">
                        </div>

                        <div class="form-group">
                            <label for="ssh_host">Host SSH *</label>
                            <input type="text" id="ssh_host" placeholder="10.10.29.152">
                        </div>

                        <div class="form-group">
                            <label for="ssh_user">Usuario *</label>
                            <input type="text" id="ssh_user" placeholder="rodavigo">
                        </div>

                        <div class="form-group">
                            <label for="ssh_port">Puerto</label>
                            <input type="text" id="ssh_port" placeholder="22" value="22">
                        </div>

                        <div class="form-group">
                            <label for="auth_type">Tipo de Autenticacion</label>
                            <select id="auth_type" onchange="toggleAuthFields()">
                                <option value="key">Clave privada</option>
                                <option value="password">Contraseña</option>
                            </select>
                        </div>

                        <div class="form-group" id="key_field">
                            <label for="ssh_key">Ruta de Clave SSH</label>
                            <input type="text" id="ssh_key" placeholder="C:/Users/Joel/Desktop/Claves/dev26.rodavigo_openssh">
                        </div>

                        <div class="form-group" id="password_field" style="display: none;">
                            <label for="ssh_password">Contraseña</label>
                            <input type="password" id="ssh_password" placeholder="Contraseña SSH">
                        </div>
                    </div>

                    <div class="button-group">
                        <button class="btn-success" onclick="saveNewConfig()">Guardar Configuración</button>
                        <button class="btn-danger" onclick="clearAllConfigs()" title="Borrar TODAS las configuraciones">Limpiar Todo</button>
                    </div>
                </div>
            </div>

            <div class="info-box">
                 <strong>Tip:</strong> Para comparar dos directorios locales:
                    1. Desactiva el checkbox "Comparar con remoto (SSH/SFTP)"
                    2. Escribe las dos rutas locales
            </div>
        </div>

        <div class="card">
            <div class="section-title">RUTAS A COMPARAR</div>

            <div class="form-section">
                <div class="form-group">
                    <label for="local_path">Ruta 1</label>
                    <input type="text" id="local_path" placeholder="C:/Code/dev26/app/Language/es">
                </div>

                <div class="form-group">
                    <label for="remote_path">Ruta 2</label>
                    <input type="text" id="remote_path" placeholder="/home/rodavigo/web/rodavigo.net/app/Language/it">
                </div>

                <div style="grid-column: 1 / -1;">
                    <input type="checkbox" id="is_remote" checked>
                    <label for="is_remote" style="display: inline; font-weight: normal;">Comparar con remoto (SSH/SFTP)</label>
                </div>
            </div>

            <div class="button-group">
                <button class="btn-primary" onclick="compareDirectories()">Comparar Directorios</button>
                <button class="btn-danger" onclick="clearForm()">Limpiar Rutas</button>
            </div>

            <div id="status" class="status"></div>
        </div>

        <div id="results_section" class="card" style="display: none;">
            <h2>Resultados</h2>
            <div id="stats" class="stats"></div>
            <div class="filter-buttons">
                <button class="filter-btn active" data-filter="all">Todos</button>
                <button class="filter-btn" data-filter="idéntico">Identicos</button>
                <button class="filter-btn" data-filter="contenido diferente">Diferentes</button>
                <button class="filter-btn" data-filter="falta en remoto">Falta remoto</button>
                <button class="filter-btn" data-filter="falta en local">Falta local</button>
            </div>
            <div id="file_list"></div>
        </div>
    </div>

    <script>
        let allFiles = [];
        let currentFilter = 'all';
        let allConfigs = {{}};

        function initConfigs() {{
            allConfigs = {configs_json};
            renderSavedConfigs();
        }}

        function renderSavedConfigs() {{
            const container = document.getElementById('saved_configs_list');
            if (!allConfigs.configurations || allConfigs.configurations.length === 0) {{
                container.innerHTML = '<p style="color: #999; font-size: 13px;">No hay configuraciones guardadas</p>';
                return;
            }}

            let html = '';
            allConfigs.configurations.forEach(config => {{
                html += `
                    <div class="config-row">
                        <div class="config-name"> ${{escapeHtml(config.name)}}</div>
                        <button class="btn-secondary btn-small" onclick="loadConfig('${{escapeHtml(config.name)}}')">Cargar</button>
                        <button class="btn-danger btn-small" onclick="deleteConfig('${{escapeHtml(config.name)}}')">Borrar</button>
                    </div>
                `;
            }});
            container.innerHTML = html;
        }}

        function loadConfig(configName) {{
            const config = allConfigs.configurations.find(c => c.name === configName);
            if (!config) return;

            document.getElementById('config_name').value = config.name;
            document.getElementById('ssh_host').value = config.hostname;
            document.getElementById('ssh_user').value = config.username;
            document.getElementById('ssh_port').value = config.port;
            document.getElementById('ssh_key').value = config.key_file || '';
            document.getElementById('ssh_password').value = config.password || '';
            document.getElementById('auth_type').value = config.auth_type;
            toggleAuthFields();
            showStatus('Configuración cargada: ' + configName, 'success');
        }}

        function saveNewConfig() {{
            const configName = document.getElementById('config_name').value.trim();
            if (!configName) {{
                showStatus('Ingresa un nombre para la configuración', 'error');
                return;
            }}

            const config = {{
                config_name: configName,
                hostname: document.getElementById('ssh_host').value.trim(),
                username: document.getElementById('ssh_user').value.trim(),
                port: parseInt(document.getElementById('ssh_port').value) || 22,
                key_file: document.getElementById('ssh_key').value.trim(),
                password: document.getElementById('ssh_password').value.trim(),
                auth_type: document.getElementById('auth_type').value,
            }};

            if (!config.hostname || !config.username) {{
                showStatus('Host y Usuario SSH son requeridos', 'error');
                return;
            }}

            fetch('/api/save_config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(config)
            }}).then(r => r.json()).then(data => {{
                if (data.status === 'saved') {{
                    showStatus('Configuración guardada: ' + configName, 'success');
                    fetch('/api/load_all_configs').then(r => r.json()).then(configs => {{
                        allConfigs = configs;
                        renderSavedConfigs();
                    }});
                }} else {{
                    showStatus('Error: ' + (data.error || 'Desconocido'), 'error');
                }}
            }}).catch(err => showStatus('Error: ' + err, 'error'));
        }}

        function deleteConfig(configName) {{
            if (!confirm('¿Borrar configuración "' + configName + '"?')) return;

            fetch('/api/delete_config', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{config_name: configName}})
            }}).then(r => r.json()).then(data => {{
                if (data.status === 'deleted') {{
                    showStatus('Configuración borrada', 'success');
                    fetch('/api/load_all_configs').then(r => r.json()).then(configs => {{
                        allConfigs = configs;
                        renderSavedConfigs();
                    }});
                    document.getElementById('config_name').value = '';
                }} else {{
                    showStatus('Error: ' + (data.error || 'Desconocido'), 'error');
                }}
            }});
        }}

        function clearAllConfigs() {{
            if (!confirm('¿Borrar TODAS las configuraciones SSH?')) return;

            fetch('/api/clear_all_configs', {{method: 'POST'}})
                .then(r => r.json())
                .then(data => {{
                    showStatus('Todas las configuraciones borradas', 'success');
                    allConfigs = {{'configurations': [], 'last_used': null}};
                    renderSavedConfigs();
                    document.getElementById('config_name').value = '';
                    document.getElementById('ssh_host').value = '';
                    document.getElementById('ssh_user').value = '';
                    document.getElementById('ssh_key').value = '';
                    document.getElementById('ssh_password').value = '';
                }});
        }}

        function toggleAuthFields() {{
            const authType = document.getElementById('auth_type').value;
            document.getElementById('key_field').style.display = authType === 'key' ? 'block' : 'none';
            document.getElementById('password_field').style.display = authType === 'password' ? 'block' : 'none';
        }}

        function compareDirectories() {{
            const data = {{
                action: 'compare',
                local_path: document.getElementById('local_path').value,
                remote_path: document.getElementById('remote_path').value,
                is_remote: document.getElementById('is_remote').checked,
                ssh_host: document.getElementById('ssh_host').value,
                ssh_user: document.getElementById('ssh_user').value,
                ssh_port: document.getElementById('ssh_port').value,
                ssh_key: document.getElementById('ssh_key').value,
                ssh_password: document.getElementById('ssh_password').value,
            }};

            showStatus('Comparando directorios...', 'loading');

            fetch('/', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(data)
            }}).then(r => r.json()).then(result => {{
                if (result.error) {{
                    showStatus('Error: ' + result.error, 'error');
                }} else {{
                    showStatus(result.message, 'success');
                    loadResults();
                }}
            }}).catch(err => showStatus('Error: ' + err, 'error'));
        }}

        function loadResults() {{
            fetch('/api/results').then(r => r.json()).then(data => {{
                allFiles = data.results;
                renderStats(data.info);
                renderResults();
                document.getElementById('results_section').style.display = 'block';
            }});
        }}

        function renderStats(info) {{
            const stats = {{ total: 0, identical: 0, different: 0, missing: 0 }};
            allFiles.forEach(f => {{
                stats.total++;
                if (f.status === 'idéntico') stats.identical++;
                else if (f.status === 'contenido diferente') stats.different++;
                else stats.missing++;
            }});

            document.getElementById('stats').innerHTML = `
                <div class="stat-card"><div class="stat-value">${{stats.total}}</div><div class="stat-label">Total</div></div>
                <div class="stat-card"><div class="stat-value">${{stats.identical}}</div><div class="stat-label">Identicos</div></div>
                <div class="stat-card"><div class="stat-value">${{stats.different}}</div><div class="stat-label">Diferentes</div></div>
                <div class="stat-card"><div class="stat-value">${{stats.missing}}</div><div class="stat-label">Faltantes</div></div>
            `;
        }}

        function renderResults() {{
            const filtered = currentFilter === 'all' ? allFiles : allFiles.filter(f => f.status === currentFilter);
            let html = '';
            filtered.forEach(file => {{
                const statusClass = 'status-' + file.status.replace(/ /g, '_');
                const isClickable = file.status === 'contenido diferente';
                const clickAttr = isClickable ? `onclick="toggleDiff(this, '${{escapeHtml(file.path)}}')"` : '';
                const clickableClass = isClickable ? ' clickable' : '';
                const clickHint = isClickable ? '<span style="font-size:11px;color:#e74c3c;margin-left:8px;">▼ ver diff</span>' : '';
                html += `
                    <div class="file-item${{clickableClass}}" ${{clickAttr}}>
                        <div class="file-header">
                            <div class="file-name">${{escapeHtml(file.path)}}${{clickHint}}</div>
                            <div class="file-status ${{statusClass}}">${{file.status}}</div>
                        </div>
                        ${{isClickable ? '<div class="diff-viewer"></div>' : ''}}
                    </div>`;
            }});
            document.getElementById('file_list').innerHTML = html || '<p>Sin archivos</p>';
        }}

        function toggleDiff(itemEl, filePath) {{
            const viewer = itemEl.querySelector('.diff-viewer');
            if (!viewer) return;

            if (viewer.classList.contains('open')) {{
                viewer.classList.remove('open');
                const hint = itemEl.querySelector('.file-name span');
                if (hint) hint.textContent = '▼ ver diff';
                return;
            }}

            viewer.classList.add('open');
            const hint = itemEl.querySelector('.file-name span');
            if (hint) hint.textContent = '▲ ocultar';

            if (viewer.dataset.loaded === '1') return;

            viewer.innerHTML = '<div class="diff-loading">Cargando diferencias...</div>';

            fetch('/api/diff/' + encodeURIComponent(filePath))
                .then(r => r.json())
                .then(data => {{
                    if (data.error) {{
                        viewer.innerHTML = `<div class="diff-loading" style="color:#c0392b">Error: ${{escapeHtml(data.error)}}</div>`;
                    }} else {{
                        viewer.innerHTML = buildDiffHtml(data);
                        viewer.dataset.loaded = '1';
                    }}
                }})
                .catch(err => {{
                    viewer.innerHTML = `<div class="diff-loading" style="color:#c0392b">Error de red: ${{err}}</div>`;
                }});
        }}

        function buildDiffHtml(data) {{
            const changes = data.changes;
            let leftRows = '';
            let rightRows = '';

            changes.forEach(row => {{
                let rowClass = 'diff-row-equal';
                if (row.type === 'replace') rowClass = 'diff-row-replace';
                else if (row.type === 'replace-only-value') rowClass = 'diff-row-replace-only-value';
                else if (row.type === 'delete') rowClass = 'diff-row-delete';
                else if (row.type === 'insert') rowClass = 'diff-row-insert';

                const leftEmpty = row.remote_line === null;
                const rightEmpty = row.local_line === null;

                const leftLineClass = leftEmpty ? 'diff-row-empty' : rowClass;
                const rightLineClass = rightEmpty ? 'diff-row-empty' : rowClass;

                leftRows += `<tr class="${{leftLineClass}}">
                    <td class="ln">${{leftEmpty ? '' : row.remote_line}}</td>
                    <td>${{escapeHtml(row.remote_text || '')}}</td>
                </tr>`;

                rightRows += `<tr class="${{rightLineClass}}">
                    <td class="ln">${{rightEmpty ? '' : row.local_line}}</td>
                    <td>${{escapeHtml(row.local_text || '')}}</td>
                </tr>`;
            }});

            return `
                <div class="diff-header">
                    <span class="diff-title">📄 ${{escapeHtml(data.path)}} — ${{data.remote_lines}} líneas remotas / ${{data.local_lines}} líneas locales</span>
                </div>
                <div class="diff-cols">
                    <div>
                        <div class="diff-col-header">← Remoto / Ruta 2</div>
                        <table class="diff-table"><tbody>${{leftRows}}</tbody></table>
                    </div>
                    <div>
                        <div class="diff-col-header">→ Local / Ruta 1</div>
                        <table class="diff-table"><tbody>${{rightRows}}</tbody></table>
                    </div>
                </div>
            `;
        }}

        function showStatus(message, type) {{
            const statusDiv = document.getElementById('status');
            statusDiv.className = `status show ${{type}}`;
            statusDiv.textContent = message;
        }}

        function clearForm() {{
            document.getElementById('local_path').value = '';
            document.getElementById('remote_path').value = '';
        }}

        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        document.querySelectorAll('.filter-btn').forEach(btn => {{
            btn.addEventListener('click', (e) => {{
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                currentFilter = e.target.dataset.filter;
                renderResults();
            }});
        }});

        initConfigs();
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
    parser = argparse.ArgumentParser(description='Comparador web de directorios')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--host', default='127.0.0.1')

    args = parser.parse_args()

    try:
        port = args.port if args.port > 0 else find_free_port()
        server = HTTPServer((args.host, port), ComparatorWebHandler)

        print(f"\n{'=' * 70}")
        print(f"Comparador de Directorios v4.2")
        print(f"Múltiples configuraciones SSH (Etiquetas PHP FIX)")
        print(f"{'=' * 70}")
        print(f"\nServidor activo en: http://{args.host}:{port}")
        print(f"\nAbre esta URL en tu navegador")
        print(f"Configuraciones guardadas en: {get_config_file()}")
        print(f"\nPresiona Ctrl+C para detener\n")

        import webbrowser
        import time
        time.sleep(1)
        webbrowser.open(f'http://{args.host}:{port}')

        server.serve_forever()

    except KeyboardInterrupt:
        print("\n\nServidor detenido")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == '__main__':
    main()

