#!/bin/bash

# Parse command line arguments
BRANCH="main"
REQ_FILE="requirements.all.txt"

while [[ $# -gt 0 ]]; do
    case $1 in
        --develop)
            BRANCH="develop"
            shift
            ;;
        --mock)
            REQ_FILE="requirements.mock.txt"
            shift
            ;;
        *)
            echo "[ERROR] Unknown option: $1"
            exit 1
            ;;
    esac
done

# Begin of script
echo "[INFO] Starting installation..."
echo "[INFO] Branch: $BRANCH"
echo "[INFO] Requirements file: $REQ_FILE"

# Check if installation directory already exists
INSTALL_DIR="$HOME/.pifanctl"
if [ -d "$INSTALL_DIR" ]; then
    echo "[INFO] Installation directory '$INSTALL_DIR' already exists."
    # Ask user if they want to remove and reinstall
    read -p "  - Do you want to remove and reinstall? (y/N): " REMOVE_INSTALL
    if [ "$REMOVE_INSTALL" = "y" ]; then
        rm -rf $INSTALL_DIR
    else
        echo "[INFO] Installation aborted. Skipping installation."
        exit 0
    fi

    echo "[INFO] Removing installation directory..."
    rm -rf $INSTALL_DIR
fi

# Clone repository to ~/.pifanctl
echo "[INFO] Cloning repository..."
git clone -b $BRANCH https://github.com/jyje/pifanctl.git $INSTALL_DIR
cd $INSTALL_DIR

# Set version information
echo "[INFO] Setting version information..."
git rev-parse --short=7 HEAD > ${INSTALL_DIR}/sources/version

# Create virtual environment
echo "[INFO] Creating virtual environment..."
cd "${INSTALL_DIR}/sources"
python3 -m venv venv

# Install dependencies
echo "[INFO] Installing dependencies..."
${INSTALL_DIR}/sources/venv/bin/pip install --upgrade pip
${INSTALL_DIR}/sources/venv/bin/pip install --upgrade -r $REQ_FILE

# Create pifanctl command
echo "[INFO] Creating pifanctl command..."
COMMAND_PATH="/usr/local/bin/pifanctl"

# Create executable with root privileges
sudo tee $COMMAND_PATH > /dev/null << EOL
#!/bin/bash
${INSTALL_DIR}/sources/venv/bin/python ${INSTALL_DIR}/sources/main.py "\$@"
EOL

# Set executable permission
sudo chmod +x $COMMAND_PATH

echo "[INFO] Installation completed! You can now use 'pifanctl' command."
