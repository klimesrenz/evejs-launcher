"""Independent Windows LAN launcher entry point."""
import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from src.lan_window import Window


def main():
    app=QApplication(sys.argv)
    app.setApplicationName('EveJS-LAN-Launcher')
    try:
        window=Window()
    except Exception as error:
        QMessageBox.critical(None,'EVE.js LAN Launcher',str(error))
        return 1
    window.show()
    return app.exec()


if __name__=='__main__':
    sys.exit(main())
