import os
import copy
import subprocess
import shutil

from datetime import datetime

from PyQt4.QtCore import Qt, QDir, QFileInfo, pyqtSignal, QModelIndex, QFileSystemWatcher
from PyQt4.QtGui import QWidget, QStandardItemModel, QStandardItem, QIcon, QMessageBox, QPixmap

from qgis.core import QgsProject, QgsMapLayerRegistry, QgsPalLabeling
from qgis.gui import QgsMapCanvas

from configmanager.ui.ui_projectwidget import Ui_Form
from configmanager.models import widgeticon, WidgetsModel, QgsLayerModel, QgsFieldModel, LayerTypeFilter, CaptureLayerFilter, CaptureLayersModel

from roam.featureform import FeatureForm

import configmanager.editorwidgets
import roam.editorwidgets
import roam.projectparser
import roam.yaml
import roam
import roam.project


readonlyvalues = [('Never', 'never'),
                  ('Always', 'always'),
                  ('When editing', 'editing'),
                  ('When inserting', 'insert')]

def layer(name):
    return QgsMapLayerRegistry.instance.mapLayersByName(name)[0]

def openfolder(folder):
    subprocess.Popen('explorer "{}"'.format(folder))

def openqgis(project):
    # TODO This needs to look in other places for QGIS.
    subprocess.Popen([r'C:\OSGeo4W\bin\qgis.bat', "--noplugins", project])

class ProjectWidget(Ui_Form, QWidget):
    SampleWidgetRole = Qt.UserRole + 1
    projectsaved = pyqtSignal()
    projectupdated = pyqtSignal()

    def __init__(self, parent=None):
        super(ProjectWidget, self).__init__(parent)
        self.setupUi(self)
        self.project = None

        self.canvas.setCanvasColor(Qt.white)
        self.canvas.enableAntiAliasing(True)
        self.canvas.setWheelAction(QgsMapCanvas.WheelZoomToMouseCursor)
        self.canvas.mapRenderer().setLabelingEngine(QgsPalLabeling())

        self.fieldsmodel = QgsFieldModel()
        self.widgetmodel = WidgetsModel()
        self.possiblewidgetsmodel = QStandardItemModel()

        self.formlayersmodel = QgsLayerModel(watchregistry=False)
        self.formlayers = CaptureLayerFilter()
        self.formlayers.setSourceModel(self.formlayersmodel)

        self.selectlayermodel = CaptureLayersModel(watchregistry=False)
        self.selectlayerfilter = LayerTypeFilter()
        self.selectlayerfilter.setSourceModel(self.selectlayermodel)
        self.selectlayermodel.dataChanged.connect(self.selectlayerschanged)

        self.layerCombo.setModel(self.formlayers)
        self.widgetCombo.setModel(self.possiblewidgetsmodel)
        self.selectLayers.setModel(self.selectlayerfilter)
        self.fieldList.setModel(self.fieldsmodel)

        self.widgetlist.setModel(self.widgetmodel)
        self.widgetlist.selectionModel().currentChanged.connect(self.updatecurrentwidget)
        self.widgetmodel.rowsRemoved.connect(self.setwidgetconfigvisiable)
        self.widgetmodel.rowsInserted.connect(self.setwidgetconfigvisiable)
        self.widgetmodel.modelReset.connect(self.setwidgetconfigvisiable)

        self.titleText.textChanged.connect(self.updatetitle)

        QgsProject.instance().readProject.connect(self._readproject)

        self.loadwidgettypes()

        self.addWidgetButton.pressed.connect(self.newwidget)
        self.removeWidgetButton.pressed.connect(self.removewidget)

        self.roamVersionLabel.setText("You are running IntraMaps Roam version {}".format(roam.__version__))

        self.openProjectFolderButton.pressed.connect(self.openprojectfolder)
        self.openinQGISButton.pressed.connect(self.openinqgis)

        self.filewatcher = QFileSystemWatcher()
        self.filewatcher.fileChanged.connect(self.qgisprojectupdated)

        self.formfolderLabel.linkActivated.connect(self.openformfolder)
        self.projectupdatedlabel.linkActivated.connect(self.reloadproject)
        self.projectupdatedlabel.hide()
        self.formtab.currentChanged.connect(self.formtabchanged)

        for item, data in readonlyvalues:
            self.readonlyCombo.addItem(item, data)

        self.setpage(4)
        self.form = None

    def openformfolder(self, url):
        openfolder(url)

    def selectlayerschanged(self, *args):
        self.formlayers.setSelectLayers(self.project.selectlayers)

    def formtabchanged(self, index):
        # preview
        if index == 1:
            self.setformpreview(self.form)

    def setprojectsfolder(self, location):
        self.projectlocationlabel.setText(location)

    def setpage(self, page):
        self.stackedWidget.setCurrentIndex(page)

    def reloadproject(self, *args):
        self.setproject(self.project)

    def qgisprojectupdated(self, path):
        self.projectupdatedlabel.show()
        self.projectupdatedlabel.setText("The QGIS project has been updated. <a href='reload'> "
                                         "Click to reload</a>. <b style=\"color:red\">Unsaved data will be lost</b>")

    def openinqgis(self):
        projectfile = self.project.projectfile
        openqgis(projectfile)

    def openprojectfolder(self):
        folder = self.project.folder
        openfolder(folder)

    def setwidgetconfigvisiable(self, *args):
        haswidgets = self.widgetmodel.rowCount() > 0
        self.widgetframe.setEnabled(haswidgets)

    def removewidget(self):
        """
        Remove the selected widget from the widgets list
        """
        widget, index = self.currentuserwidget
        if index.isValid():
            self.widgetmodel.removeRow(index.row())

    def newwidget(self):
        """
        Create a new widget.  The default is a list.
        """
        widget = {}
        widget['widget'] = 'List'
        # Grab the first field.
        widget['field'] = self.fieldsmodel.index(0, 0).data(QgsFieldModel.FieldNameRole)
        index = self.widgetmodel.addwidget(widget)
        self.widgetlist.setCurrentIndex(index)

    def loadwidgettypes(self):
        self.widgetCombo.blockSignals(True)
        for widgettype in roam.editorwidgets.supportedwidgets:
            try:
                configclass = configmanager.editorwidgets.widgetconfigs[widgettype.widgettype]
            except KeyError:
                continue

            configwidget = configclass()
            item = QStandardItem(widgettype.widgettype)
            item.setData(configwidget, Qt.UserRole)
            item.setData(widgettype.widgettype, Qt.UserRole + 1)
            item.setIcon(QIcon(widgeticon(widgettype.widgettype)))
            self.widgetCombo.model().appendRow(item)
            self.widgetstack.addWidget(configwidget)
        self.widgetCombo.blockSignals(False)

    @property
    def currentform(self):
        """
        Return the current selected form.
        """
        return self.form

    @property
    def currentuserwidget(self):
        """
        Return the selected user widget.
        """
        index = self.widgetlist.selectionModel().currentIndex()
        return index.data(Qt.UserRole), index

    @property
    def currentwidgetconfig(self):
        """
        Return the selected widget in the widget combo.
        """
        index = self.widgetCombo.currentIndex()
        index = self.possiblewidgetsmodel.index(index, 0)
        return index.data(Qt.UserRole), index, index.data(Qt.UserRole + 1)

    def _save_selectedwidget(self, index):
        configwidget, index, widgettype = self.currentwidgetconfig
        widget, index = self.currentuserwidget
        if not widget:
            return

        widget['widget'] = widgettype
        widget['required'] = self.requiredCheck.isChecked()
        row = self.fieldList.currentIndex()
        field = self.fieldsmodel.index(row, 0).data(QgsFieldModel.FieldNameRole)
        widget['field'] = field
        widget['config'] = configwidget.getconfig()
        widget['name'] = self.nameText.text()
        widget['read-only-rules'] = [self.readonlyCombo.itemData(self.readonlyCombo.currentIndex())]
        widget['hidden'] = self.hiddenCheck.isChecked()

        self.widgetmodel.setData(index, widget, Qt.UserRole)

    def _save_default(self):
        widget, index = self.currentuserwidget
        default = self.defaultvalueText.text()
        widget['default'] = default
        self.widgetmodel.setData(index, widget, Qt.UserRole)

    def _save_selectionlayers(self, index, layer, value):
        config = self.project.settings

        self.selectlayermodel.dataChanged.emit(index, index)

    def _save_formtype(self, index):
        formtype = self.formtypeCombo.currentText()
        form = self.currentform
        form.settings['type'] = formtype

    def _save_formname(self, text):
        """
        Save the form label to the settings file.
        """
        try:
            form = self.currentform
            if form is None:
                return
            form.settings['label'] = text
            self.projectupdated.emit()
        except IndexError:
            return

    def _save_layer(self, index):
        """
        Save the selected layer to the settings file.
        """
        index = self.formlayers.index(index, 0)
        layer = index.data(Qt.UserRole)
        if not layer:
            return

        form = self.currentform
        if form is None:
            return

        form.settings['layer'] = layer.name()
        self.updatefields(layer)

    def setproject(self, project, loadqgis=True):
        """
        Set the widgets active project.
        """
        self.filewatcher.removePaths(self.filewatcher.files())
        self.projectupdatedlabel.hide()
        self.startsettings = copy.deepcopy(project.settings)
        self.project = project
        self.projectlabel.setText(project.name)
        self.versionText.setText(project.version)
        self.selectlayermodel.config = project.settings
        self.formlayers.setSelectLayers(self.project.selectlayers)
        pixmap = QPixmap(project.splash)
        w = self.splashlabel.width()
        h = self.splashlabel.height()
        self.splashlabel.setPixmap(pixmap.scaled(w,h, Qt.KeepAspectRatio))
        if loadqgis:
            self.loadqgisproject(project, self.project.projectfile)
        else:
            self._updateforproject(self.project)
        self.filewatcher.addPath(self.project.projectfile)

    def loadqgisproject(self, project, projectfile):
        self._closeqgisproject()
        QDir.setCurrent(os.path.dirname(project.projectfile))
        fileinfo = QFileInfo(project.projectfile)
        QgsProject.instance().read(fileinfo)

    def _closeqgisproject(self):
        if self.canvas.isDrawing():
            return

        self.canvas.freeze(True)
        self.formlayersmodel.removeall()
        self.selectlayermodel.removeall()
        QgsMapLayerRegistry.instance().removeAllMapLayers()
        self.canvas.freeze(False)

    def _readproject(self, doc):
        parser = roam.projectparser.ProjectParser(doc)
        canvasnode = parser.canvasnode
        self.canvas.mapRenderer().readXML(canvasnode)
        self.canvaslayers = parser.canvaslayers()
        self.canvas.setLayerSet(self.canvaslayers)
        self.canvas.updateScale()
        self.canvas.freeze(False)
        self.canvas.refresh()
        layers = QgsMapLayerRegistry.instance().mapLayers().values()
        self.formlayersmodel.addlayers(layers, removeall=True)
        self.selectlayermodel.addlayers(layers, removeall=True)
        self._updateforproject(self.project)

    def _updateforproject(self, project):
        self.titleText.setText(project.name)
        self.descriptionText.setPlainText(project.description)

    def swapwidgetconfig(self, index):
        self.updatewidgetconfig({})

    def updatetitle(self, text):
        self.project.settings['title'] = text
        self.projectlabel.setText(text)
        self.projectupdated.emit()

    def updatewidgetconfig(self, config):
        widgetconfig, index, widgettype = self.currentwidgetconfig
        self.setconfigwidget(widgetconfig, config)

    def setformpreview(self, form):
        def removewidget():
            item = self.frame_2.layout().itemAt(0)
            if item and item.widget():
                item.widget().setParent(None)

        removewidget()

        featureform = FeatureForm.from_form(form, form.settings, None, {})

        self.frame_2.layout().addWidget(featureform)

    def setform(self, form):
        """
        Update the UI with the currently selected form.
        """
        def connectsignals():
            self.formLabelText.textChanged.connect(self._save_formname)
            self.layerCombo.currentIndexChanged.connect(self._save_layer)
            self.formtypeCombo.currentIndexChanged.connect(self._save_formtype)

            #widget settings
            self.fieldList.currentIndexChanged.connect(self._save_selectedwidget)
            self.fieldList.editTextChanged.connect(self._save_selectedwidget)
            self.requiredCheck.toggled.connect(self._save_selectedwidget)
            self.defaultvalueText.textChanged.connect(self._save_default)
            self.widgetCombo.currentIndexChanged.connect(self._save_selectedwidget)
            self.widgetCombo.currentIndexChanged.connect(self.swapwidgetconfig)
            self.nameText.textChanged.connect(self._save_selectedwidget)
            self.readonlyCombo.currentIndexChanged.connect(self._save_selectedwidget)
            self.hiddenCheck.toggled.connect(self._save_selectedwidget)

        def disconnectsignals():
            try:
                self.formLabelText.textChanged.disconnect(self._save_formname)
                self.layerCombo.currentIndexChanged.disconnect(self._save_layer)
                self.formtypeCombo.currentIndexChanged.disconnect(self._save_formtype)

                #widget settings
                self.fieldList.currentIndexChanged.disconnect(self._save_selectedwidget)
                self.fieldList.editTextChanged.disconnect(self._save_selectedwidget)
                self.requiredCheck.toggled.disconnect(self._save_selectedwidget)
                self.defaultvalueText.textChanged.disconnect(self._save_default)
                self.widgetCombo.currentIndexChanged.disconnect(self._save_selectedwidget)
                self.widgetCombo.currentIndexChanged.disconnect(self.swapwidgetconfig)
                self.nameText.textChanged.disconnect(self._save_selectedwidget)
                self.readonlyCombo.currentIndexChanged.disconnect(self._save_selectedwidget)
                self.hiddenCheck.toggled.disconnect(self._save_selectedwidget)
            except TypeError:
                pass

        disconnectsignals()

        settings = form.settings
        label = settings['label']
        layer = settings.get('layer', None)
        formtype = settings.get('type', 'auto')
        widgets = settings.get('widgets', [])

        if not layer:
            print "No layer current set, setting the first one."
            index = self.formlayers.index(0,0)
            layer = index.data(Qt.UserRole)
            layername = layer.name()
            settings['layer'] = layername

        self.formLabelText.setText(label)
        folderurl = "<a href='{path}'>{name}</a>".format(path=form.folder, name=os.path.basename(form.folder))
        self.formfolderLabel.setText(folderurl)
        index = self.formlayersmodel.findlayer(layer)
        index = self.formlayers.mapFromSource(index)
        self.layerCombo.setCurrentIndex(index.row())
        self.updatefields(index.data(Qt.UserRole))

        index = self.formtypeCombo.findText(formtype)
        if index == -1:
            self.formtypeCombo.insertItem(0, formtype)
            self.formtypeCombo.setCurrentIndex(0)
        else:
            self.formtypeCombo.setCurrentIndex(index)

        self.widgetmodel.loadwidgets(widgets)

        # Set the first widget
        index = self.widgetmodel.index(0, 0)
        if index.isValid():
            self.widgetlist.setCurrentIndex(index)
            self.updatecurrentwidget(index, None)

        connectsignals()
        self.form = form

    def updatefields(self, layer):
        """
        Update the UI with the fields for the selected layer.
        """
        self.fieldsmodel.setLayer(layer)

    def setconfigwidget(self, configwidget, config):
        """
        Set the active config widget.
        """

        try:
            configwidget.widgetdirty.disconnect(self._save_selectedwidget)
        except TypeError:
            pass

        self.descriptionLabel.setText(configwidget.description)
        self.widgetstack.setCurrentWidget(configwidget)
        configwidget.setconfig(config)

        configwidget.widgetdirty.connect(self._save_selectedwidget)

    def updatecurrentwidget(self, index, _):
        """
        Update the UI with the config for the current selected widget.
        """
        if not index.isValid():
            return

        widget = index.data(Qt.UserRole)
        widgettype = widget['widget']
        field = widget['field']
        required = widget.get('required', False)
        name = widget.get('name', field)
        default = widget.get('default', '')
        readonly = widget.get('read-only-rules', [])
        hidden = widget.get('hidden', False)

        try:
            data = readonly[0]
        except:
            data = 'never'

        self.readonlyCombo.blockSignals(True)
        index = self.readonlyCombo.findData(data)
        self.readonlyCombo.setCurrentIndex(index)
        self.readonlyCombo.blockSignals(False)

        self.defaultvalueText.blockSignals(True)
        if not isinstance(default, dict):
            self.defaultvalueText.setText(default)
        else:
            # TODO Handle the more advanced default values.
            pass
        self.defaultvalueText.blockSignals(False)

        self.nameText.blockSignals(True)
        self.nameText.setText(name)
        self.nameText.blockSignals(False)

        self.requiredCheck.blockSignals(True)
        self.requiredCheck.setChecked(required)
        self.requiredCheck.blockSignals(False)

        self.hiddenCheck.blockSignals(True)
        self.hiddenCheck.setChecked(hidden)
        self.hiddenCheck.blockSignals(False)

        if not field is None:
            self.fieldList.blockSignals(True)
            index = self.fieldList.findData(field.lower(), QgsFieldModel.FieldNameRole)
            if index > -1:
                self.fieldList.setCurrentIndex(index)
            else:
                self.fieldList.setEditText(field)
            self.fieldList.blockSignals(False)

        index = self.widgetCombo.findText(widgettype)
        self.widgetCombo.blockSignals(True)
        if index > -1:
            self.widgetCombo.setCurrentIndex(index)
        self.widgetCombo.blockSignals(False)

        self.updatewidgetconfig(config=widget.get('config', {}))

    def _saveproject(self):
        """
        Save the project config to disk.
        """
        title = self.titleText.text()
        description = self.descriptionText.toPlainText()
        version = str(self.versionText.text())

        settings = self.project.settings
        settings['title'] = title
        settings['description'] = description
        settings['version'] = version

        self.project.save()
        self.projectsaved.emit()




