#!/usr/bin/env python3
"""
Verification script for Asana Obsidian Exporter
Checks setup, configuration, and API connectivity before export.
"""

import os
import sys
import json
from pathlib import Path
import subprocess


class VerificationChecklist:
    """Run pre-export verification checks."""
    
    def __init__(self):
        self.checks_passed = 0
        self.checks_failed = 0
        self.warnings = 0
    
    def header(self, text):
        """Print section header."""
        print("\n" + "="*60)
        print(f"  {text}")
        print("="*60)
    
    def success(self, text):
        """Print success message."""
        print(f"✅ {text}")
        self.checks_passed += 1
    
    def error(self, text):
        """Print error message."""
        print(f"❌ {text}")
        self.checks_failed += 1
    
    def warning(self, text):
        """Print warning message."""
        print(f"⚠️  {text}")
        self.warnings += 1
    
    def info(self, text):
        """Print info message."""
        print(f"ℹ️  {text}")
    
    def check_python(self):
        """Check Python version."""
        self.header("1. Python Environment")
        
        version = sys.version_info
        print(f"Python version: {version.major}.{version.minor}.{version.micro}")
        
        if version.major >= 3 and version.minor >= 8:
            self.success(f"Python {version.major}.{version.minor} supported")
        else:
            self.error(f"Python {version.major}.{version.minor} too old (3.8+ required)")
            return False
        
        return True
    
    def check_dependencies(self):
        """Check required packages."""
        self.header("2. Dependencies")
        
        required = ["requests"]
        optional = ["dotenv"]
        
        all_ok = True
        
        for package in required:
            try:
                __import__(package)
                self.success(f"{package} installed")
            except ImportError:
                self.error(f"{package} NOT installed (required)")
                self.info(f"  Fix: pip install {package}")
                all_ok = False
        
        for package in optional:
            try:
                __import__(package)
                self.success(f"{package} installed (optional)")
            except ImportError:
                self.warning(f"{package} not installed (optional)")
                self.info(f"  For .env support: pip install python-dotenv")
        
        return all_ok
    
    def check_asana_token(self):
        """Check Asana token configuration."""
        self.header("3. Asana Token")
        
        token = os.getenv("ASANA_TOKEN")
        
        # Check .env file
        if Path(".env").exists():
            self.success(".env file found")
            try:
                from dotenv import load_dotenv
                load_dotenv()
                token = os.getenv("ASANA_TOKEN")
            except:
                pass
        
        if not token:
            self.error("ASANA_TOKEN not set")
            self.info("  Set environment variable: export ASANA_TOKEN=your_token")
            self.info("  Or create .env file with: ASANA_TOKEN=your_token")
            return False
        
        # Validate token format
        if len(token) < 20:
            self.error("Token too short (should be ~32 characters)")
            return False
        
        if not all(c.isalnum() or c in '_-' for c in token):
            self.error("Token contains invalid characters")
            return False
        
        self.success(f"Token configured (length: {len(token)} chars)")
        return True
    
    def check_api_connectivity(self, token):
        """Test API connectivity."""
        self.header("4. API Connectivity")
        
        import requests
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        
        # Test authentication
        try:
            response = requests.get(
                "https://app.asana.com/api/1.0/users/me",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                user = response.json()
                name = user.get("data", {}).get("name", "Unknown")
                self.success(f"Successfully authenticated as: {name}")
                return True
            
            elif response.status_code == 401:
                self.error("Invalid token (401 Unauthorized)")
                return False
            
            else:
                self.error(f"API error: {response.status_code}")
                self.info(f"  Response: {response.text[:100]}")
                return False
        
        except requests.exceptions.ConnectionError:
            self.error("Cannot connect to Asana API")
            self.info("  Check your internet connection")
            return False
        
        except requests.exceptions.Timeout:
            self.error("Request timeout")
            self.info("  Asana API may be temporarily unavailable")
            return False
        
        except Exception as e:
            self.error(f"API test failed: {e}")
            return False
    
    def check_workspace(self, token):
        """Check available projects."""
        self.header("5. Asana Workspace")
        
        import requests
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        
        try:
            response = requests.get(
                "https://app.asana.com/api/1.0/projects",
                headers=headers,
                params={"limit": 10},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                projects = data.get("data", [])
                
                if projects:
                    self.success(f"Found {len(projects)} + projects")
                    for i, p in enumerate(projects[:3], 1):
                        self.info(f"  {i}. {p.get('name', 'Unnamed')}")
                    if len(projects) > 3:
                        self.info(f"  ... and {len(projects) - 3} more")
                    return True
                else:
                    self.warning("No projects found in workspace")
                    self.info("  Create a project in Asana first")
                    return True
            else:
                self.error(f"Failed to fetch projects: {response.status_code}")
                return False
        
        except Exception as e:
            self.error(f"Failed to check workspace: {e}")
            return False
    
    def check_vault_path(self, vault_path=None):
        """Check vault output path."""
        self.header("6. Vault Configuration")
        
        if not vault_path:
            self.warning("No vault path specified (will use current directory)")
            return True
        
        vault_path = Path(vault_path).expanduser()
        
        if vault_path.exists():
            self.success(f"Vault path exists: {vault_path}")
            
            # Check if directory is writable
            if os.access(vault_path, os.W_OK):
                self.success("Vault path is writable")
            else:
                self.error("Vault path is not writable")
                return False
            
            # Check for existing state
            state_file = vault_path / ".asana_export_state.json"
            if state_file.exists():
                self.info(f"Existing state file found (incremental backup)")
                try:
                    with open(state_file) as f:
                        state = json.load(f)
                    exported_count = len(state.get("exported_tasks", {}))
                    self.info(f"  Previously exported: {exported_count} tasks")
                except:
                    pass
        else:
            try:
                vault_path.mkdir(parents=True, exist_ok=True)
                self.success(f"Created vault path: {vault_path}")
            except Exception as e:
                self.error(f"Cannot create vault path: {e}")
                return False
        
        return True
    
    def check_disk_space(self, vault_path=None):
        """Check available disk space."""
        self.header("7. Disk Space")
        
        if not vault_path:
            vault_path = Path.cwd()
        else:
            vault_path = Path(vault_path).expanduser()
        
        try:
            stat = os.statvfs(str(vault_path))
            free_bytes = stat.f_bavail * stat.f_frsize
            free_gb = free_bytes / (1024**3)
            
            if free_gb > 1:
                self.success(f"Sufficient disk space: {free_gb:.2f} GB free")
            elif free_gb > 0.1:
                self.warning(f"Low disk space: {free_gb:.2f} GB free")
            else:
                self.error(f"Insufficient disk space: {free_gb:.2f} GB")
                return False
        
        except Exception as e:
            self.warning(f"Could not check disk space: {e}")
        
        return True
    
    def check_git(self):
        """Check Git setup for version control."""
        self.header("8. Git Setup (Optional)")
        
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.success(f"Git installed: {result.stdout.strip()}")
            else:
                self.warning("Git not found (recommended for backups)")
        except:
            self.warning("Git not found (recommended for backups)")
    
    def print_summary(self):
        """Print verification summary."""
        self.header("Verification Summary")
        
        total = self.checks_passed + self.checks_failed
        
        print(f"✅ Passed:  {self.checks_passed}/{total}")
        if self.checks_failed > 0:
            print(f"❌ Failed:  {self.checks_failed}/{total}")
        if self.warnings > 0:
            print(f"⚠️  Warnings: {self.warnings}")
        
        print()
        
        if self.checks_failed == 0:
            print("🎉 All checks passed! Ready to export.")
            return True
        else:
            print("⚠️  Please fix the errors above before running export.")
            return False
    
    def run_all_checks(self, token=None, vault_path=None):
        """Run all verification checks."""
        print("\n")
        print("╔" + "═"*58 + "╗")
        print("║" + " "*58 + "║")
        print("║" + "  Asana → Obsidian Export - Verification Checklist".center(58) + "║")
        print("║" + " "*58 + "║")
        print("╚" + "═"*58 + "╝")
        
        # Run checks
        if not self.check_python():
            return False
        
        if not self.check_dependencies():
            return False
        
        if not self.check_asana_token():
            return False
        
        token = os.getenv("ASANA_TOKEN")
        
        if not self.check_api_connectivity(token):
            return False
        
        if not self.check_workspace(token):
            return False
        
        if not self.check_vault_path(vault_path):
            return False
        
        if not self.check_disk_space(vault_path):
            return False
        
        self.check_git()
        
        # Print summary
        success = self.print_summary()
        
        return success


def main():
    import argparse
    from dotenv import load_dotenv
    
    parser = argparse.ArgumentParser(
        description="Verify Asana Obsidian Exporter setup"
    )
    parser.add_argument(
        "--vault",
        help="Path to Obsidian vault"
    )
    parser.add_argument(
        "--token",
        help="Asana Personal Access Token (or set ASANA_TOKEN env var)"
    )
    
    args = parser.parse_args()
    
    # Load .env if exists
    if Path(".env").exists():
        load_dotenv()
    
    # Get token
    token = args.token or os.getenv("ASANA_TOKEN")
    if token:
        os.environ["ASANA_TOKEN"] = token
    
    # Run checks
    checker = VerificationChecklist()
    success = checker.run_all_checks(token=token, vault_path=args.vault)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
