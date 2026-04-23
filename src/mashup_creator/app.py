from PyQt6 import QtGui, QtWidgets

from . import constants as c
from .ui import MainWindow


def main() -> None:
    for folder in c.DIRS:
        folder.mkdir(parents=True, exist_ok=True)

    app = QtWidgets.QApplication([])
    if c.ICON_ICO_PATH.exists():
        app.setWindowIcon(QtGui.QIcon(str(c.ICON_ICO_PATH)))
    elif c.ICON_PATH.exists():
        app.setWindowIcon(QtGui.QIcon(str(c.ICON_PATH)))

    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
