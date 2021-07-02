import json
import logging
import os
import random
import requests
import time
import unittest
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

#
# OnDemand
#

class OnDemand(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "OnDemand"
    self.parent.categories = ["Wizards"]
    self.parent.dependencies = []
    self.parent.contributors = ["Steve Pieper (Isomics, Inc.)"]
    self.parent.helpText = """
Create compute instances with Slicer pre-configured.
See more information in <a href="https://github.com/organization/projectname#OnDemand">module documentation</a>.
"""
    self.parent.acknowledgementText = """
Developed in part with funding from the NCI Imaging Data Commons contract number 19X037Q
from Leidos Biomedical Research under Task Order HHSN26100071 from NCI.

This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
"""


#
# OnDemandWidget
#

class OnDemandWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent=None):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.__init__(self, parent)
    VTKObservationMixin.__init__(self)  # needed for parameter node observation
    self.logic = None
    self._parameterNode = None
    self._updatingGUIFromParameterNode = False

  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

    # Load widget from .ui file (created by Qt Designer).
    # Additional widgets can be instantiated manually and added to self.layout.
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/OnDemand.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
    # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
    # "setMRMLScene(vtkMRMLScene*)" slot.
    uiWidget.setMRMLScene(slicer.mrmlScene)

    uiWidget.hide()

    # Create logic class. Logic implements all computations that should be possible to run
    # in batch mode, without a graphical user interface.
    self.logic = OnDemandLogic()

    # Connections

    # These connections ensure that we update parameter node when scene is closed
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    # (in the selected parameter node).
    self.ui.inputSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
    self.ui.outputSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
    self.ui.imageThresholdSliderWidget.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
    self.ui.invertOutputCheckBox.connect("toggled(bool)", self.updateParameterNodeFromGUI)
    self.ui.invertedOutputSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)

    # Buttons
    self.ui.applyButton.connect('clicked(bool)', self.onApplyButton)

    # Make sure parameter node is initialized (needed for module reload)
    self.initializeParameterNode()

  def cleanup(self):
    """
    Called when the application closes and the module widget is destroyed.
    """
    self.removeObservers()

  def enter(self):
    """
    Called each time the user opens this module.
    """
    # Make sure parameter node exists and observed
    self.initializeParameterNode()

  def exit(self):
    """
    Called each time the user opens a different module.
    """
    # Do not react to parameter node changes (GUI wlil be updated when the user enters into the module)
    self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

  def onSceneStartClose(self, caller, event):
    """
    Called just before the scene is closed.
    """
    # Parameter node will be reset, do not use it anymore
    self.setParameterNode(None)

  def onSceneEndClose(self, caller, event):
    """
    Called just after the scene is closed.
    """
    # If this module is shown while the scene is closed then recreate a new parameter node immediately
    if self.parent.isEntered:
      self.initializeParameterNode()

  def initializeParameterNode(self):
    """
    Ensure parameter node exists and observed.
    """
    # Parameter node stores all user choices in parameter values, node selections, etc.
    # so that when the scene is saved and reloaded, these settings are restored.

    self.setParameterNode(self.logic.getParameterNode())

    # Select default input nodes if nothing is selected yet to save a few clicks for the user
    if not self._parameterNode.GetNodeReference("InputVolume"):
      firstVolumeNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLScalarVolumeNode")
      if firstVolumeNode:
        self._parameterNode.SetNodeReferenceID("InputVolume", firstVolumeNode.GetID())

  def setParameterNode(self, inputParameterNode):
    """
    Set and observe parameter node.
    Observation is needed because when the parameter node is changed then the GUI must be updated immediately.
    """

    if inputParameterNode:
      self.logic.setDefaultParameters(inputParameterNode)

    # Unobserve previously selected parameter node and add an observer to the newly selected.
    # Changes of parameter node are observed so that whenever parameters are changed by a script or any other module
    # those are reflected immediately in the GUI.
    if self._parameterNode is not None:
      self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    self._parameterNode = inputParameterNode
    if self._parameterNode is not None:
      self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    # Initial GUI update
    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self, caller=None, event=None):
    """
    This method is called whenever parameter node is changed.
    The module GUI is updated to show the current state of the parameter node.
    """

    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    # Make sure GUI changes do not call updateParameterNodeFromGUI (it could cause infinite loop)
    self._updatingGUIFromParameterNode = True

    # All the GUI updates are done
    self._updatingGUIFromParameterNode = False

  def updateParameterNodeFromGUI(self, caller=None, event=None):
    """
    This method is called when the user makes any change in the GUI.
    The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
    """

    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

    self._parameterNode.SetNodeReferenceID("InputVolume", self.ui.inputSelector.currentNodeID)
    self._parameterNode.SetNodeReferenceID("OutputVolume", self.ui.outputSelector.currentNodeID)
    self._parameterNode.SetParameter("Threshold", str(self.ui.imageThresholdSliderWidget.value))
    self._parameterNode.SetParameter("Invert", "true" if self.ui.invertOutputCheckBox.checked else "false")
    self._parameterNode.SetNodeReferenceID("OutputVolumeInverse", self.ui.invertedOutputSelector.currentNodeID)

    self._parameterNode.EndModify(wasModified)

  def onApplyButton(self):
    """
    Run processing when user clicks "Apply" button.
    """
    try:

      # Compute output
      self.logic.process(self.ui.inputSelector.currentNode(), self.ui.outputSelector.currentNode(),
                         self.ui.imageThresholdSliderWidget.value, self.ui.invertOutputCheckBox.checked)

      # Compute inverted output (if needed)
      if self.ui.invertedOutputSelector.currentNode():
        # If additional output volume is selected then result with inverted threshold is written there
        self.logic.process(self.ui.inputSelector.currentNode(),
                           self.ui.invertedOutputSelector.currentNode(),
                           self.ui.imageThresholdSliderWidget.value,
                           not self.ui.invertOutputCheckBox.checked, showResult=False)

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: " + str(e))
      import traceback
      traceback.print_exc()


class GoogleCloudPlatform(object):

  def __init__(self, project):
    self.project = project

  def gcloud(self, subcommand):
    process = qt.QProcess()
    process.start("gcloud", subcommand.split())
    process.waitForFinished()
    result = process.readAllStandardOutput().data().decode()
    error = process.readAllStandardError().data().decode()
    if process.exitStatus() != process.NormalExit:
      print(f"gcloud error: {error}")
    else:
      if error != "":
        print(f"gcloud warning: {error}")
    return result

  def projects(self):
    return self.gcloud("projects list").split("\n")[1:]

  def datasets(self):
    return self.gcloud(f"--project {self.project} healthcare datasets list").split("\n")[1:]

  def dicomStores(self, dataset):
    return self.gcloud(f"--project {self.project} healthcare dicom-stores list --dataset {dataset}").split("\n")[1:]

  def instances(self):
    return self.gcloud(f"--project {self.project} instances list").split("\n")[1:]

  def createInstance(self, instanceID):
    image = "slicermachine-2021-06-16t16-04-21"
    return self.gcloud(f"--project {self.project} compute instances create {instanceID} --machine-type=n1-standard-8 --accelerator=type=nvidia-tesla-k80,count=1 --image={image} --image-project=idc-sandbox-000 --boot-disk-size=200GB --boot-disk-type=pd-balanced --maintenance-policy=TERMINATE")

  def instanceStatus(self, instanceID):
    description = json.loads(self.gcloud(f"--project {self.project} compute instances describe --format json {instanceID}"))
    return description['status']

  def instanceSSHTunnel(self, instanceID, port):
    process = qt.QProcess()
    subcommand = f"--project {self.project} compute ssh {instanceID} -- -L {port}:localhost:6080"
    process.start("gcloud", subcommand.split())
    return process

  def token(self):
    return self.gcloud("auth print-access-token").strip()


#
# OnDemandLogic
#

class OnDemandLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self):
    """
    Called when the logic class is instantiated. Can be used for initializing member variables.
    """
    ScriptedLoadableModuleLogic.__init__(self)
    self.gcp = GoogleCloudPlatform("idc-sandbox-000")

  def setDefaultParameters(self, inputParameterNode):
    pass

  def launchSlicer(self, instanceID):
    print(f"Launching {instanceID}...")
    self.gcp.createInstance(instanceID)
    print(f"Launched {instanceID}")


class OnDemandApp(object):
  def __init__(self):
    """
    Called when the logic class is instantiated. Can be used for initializing member variables.
    """
    ScriptedLoadableModuleLogic.__init__(self)

    self.project = "idc-sandbox-000"
    self.logic = OnDemandLogic()

  def main(self):

    self.mainWindow = slicer.util.loadUI(slicer.modules.OnDemandWidget.resourcePath('UI/OnDemandMainWindow.ui'))

    f = qt.QFile(slicer.modules.OnDemandWidget.resourcePath('QSS/OnDemand.qss'))
    f.open(qt.QFile.ReadOnly | qt.QFile.Text)
    styleText = qt.QTextStream(f)
    styleSheet = styleText.readAll()
    self.mainWindow.setStyleSheet(styleSheet)

    self.ui = slicer.util.childWidgetVariables(self.mainWindow)
    self.ui.logo.setPixmap(qt.QPixmap(slicer.modules.OnDemandWidget.resourcePath('Icons/logo.png')))

    self.ui.rocketButton = slicer.util.loadUI(slicer.modules.OnDemandWidget.resourcePath('UI/rocketButton.ui'))
    self.ui.robotButton = slicer.util.loadUI(slicer.modules.OnDemandWidget.resourcePath('UI/robotButton.ui'))
    self.ui.tunnelButton = slicer.util.loadUI(slicer.modules.OnDemandWidget.resourcePath('UI/tunnelButton.ui'))
    self.ui.shutDownButton = slicer.util.loadUI(slicer.modules.OnDemandWidget.resourcePath('UI/shutDownButton.ui'))

    self.ui.instancesWidgetVerticalLayout.addWidget(self.ui.rocketButton)
    self.ui.instancesWidgetVerticalLayout.addWidget(self.ui.robotButton)
    self.ui.instancesWidgetVerticalLayout.addWidget(self.ui.tunnelButton)
    self.ui.instancesWidgetVerticalLayout.addWidget(self.ui.shutDownButton)

    self.ui.launchButton.show()
    self.ui.rocketButton.hide()
    self.ui.robotButton.hide()
    self.ui.tunnelButton.hide()
    self.ui.shutDownButton.hide()

    self.ui.launchButton.connect("clicked()", self.launchAndConnect)
    self.ui.shutDownButton.connect("clicked()", self.disconnectAndDestroy)

    self.mainWindow.show()

  def onCreateInstance(self):
    self.ui.launchButton.hide()
    self.ui.rocketButton.show()
    self.ui.statusbar.showMessage('Creating an On Demand Machine...')

  def onLoopInstanceStatus(self):
    self.ui.rocketButton.hide()
    self.ui.robotButton.show()
    self.ui.statusbar.showMessage('Setting up the On Demand Machine...')

  def onCreateTunnel(self):
    self.ui.robotButton.hide()
    self.ui.tunnelButton.show()
    self.ui.statusbar.showMessage('Establishing a secure connection...')

  def onInstanceRunning(self):
    self.ui.tunnelButton.hide()
    self.ui.shutDownButton.show()
    self.ui.statusbar.showMessage('The On Demand Machine is online.')

  def launchAndConnect(self):
    startTime = time.time()
    number = random.randint(1, 1000)
    instanceID = f"sdp-slicer-on-demand-{number}"
    self.onCreateInstance()  # Change launch button to rocket button
    self.logic.launchSlicer(instanceID)
    launchSlicerTime = time.time()
    self.onLoopInstanceStatus()  # Change rocket button to robot button
    waitTime = 0
    while waitTime < 300:
      waitTime += 1
      status = self.logic.gcp.instanceStatus(instanceID)
      if status not in ["PENDING", "STAGING"]:
        break
      else:
        print(f"Status: {status} {waitTime}")
    self.onCreateTunnel()  # Change robot button to lock with key button
    port = 6080 + number
    self.sshProcess = self.logic.gcp.instanceSSHTunnel(instanceID, port)
    instanceSSHTunnelTime = time.time()
    rootUrl = f"http://localhost:{port}"
    vncQUrl = qt.QUrl(f"{rootUrl}/vnc.html?autoconnect=true")
    waitTime = 0
    while waitTime < 300:
      waitTime += 1
      try:
        reply = requests.get(rootUrl)
        break
      except requests.exceptions.ConnectionError:
        print("Connection not ready")
      time.sleep(1)
      print(f"Waiting for server ({waitTime})")
    bootTime = time.time()
    qt.QDesktopServices.openUrl(vncQUrl)
    print(f"launchSlicerTime = {launchSlicerTime - startTime}")
    print(f"instanceSSHTunnelTime = {instanceSSHTunnelTime - launchSlicerTime}")
    print(f"bootTime = {bootTime - instanceSSHTunnelTime}")
    print(f"Total Time = {bootTime - startTime}")
    self.onInstanceRunning()  # Change lock with key button to shut down button

  def disconnectAndDestroy(self):
    """TODO: Implement instance liquidation."""
    pass
#
# OnDemandTest
#

class OnDemandTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    pass

  def runTest(self):
    app = OnDemandApp()
    app.main()
    slicer.modules.app = app

