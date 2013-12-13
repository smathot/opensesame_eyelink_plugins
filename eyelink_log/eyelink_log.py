"""
This file is part of OpenSesame.

OpenSesame is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

OpenSesame is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with OpenSesame.  If not, see <http://www.gnu.org/licenses/>.
"""

from libopensesame import item, exceptions
from libqtopensesame import qtplugin
import os.path
from PyQt4 import QtGui, QtCore

class eyelink_log(item.item):

	"""A plug-in to log information to the EyeLink"""

	def __init__(self, name, experiment, string=None):

		"""
		Constructor

		Arguments:
		name		--	item name
		experiment	--	an experiment object

		Keyword arguments:
		string		--	a definitional string (default=None)
		"""

		self.item_type = "eyelink_log"
		self.msg = ""
		self.auto_log = 'no'
		self.throttle = 2
		self.description = \
			"Message log for the Eyelink series of eye trackers (SR-Research)"
		item.item.__init__(self, name, experiment, string)

	def prepare(self):

		"""
		Prepare the plug-in

		Returns:
		True
		"""

		item.item.prepare(self)
		if not hasattr(self.experiment, "eyelink"):
			raise exceptions.runtime_error( \
				"Please connect to the eyelink using the the eyelink_calibrate plugin before using any other eyelink plugins")
		self._msg = self.msg.split("\n")
		return True

	def run(self):

		"""
		Run the plug-in

		Returns:
		True
		"""

		self.set_item_onset()
		for msg in self._msg:
			self.experiment.eyelink.log(self.eval_text(msg))
			self.sleep(self.throttle)
		if self.auto_log == 'yes':
			for logvar, _val, item in self.experiment.var_list():
				val = self.get_check(logvar, default='NA')
				self.experiment.eyelink.log('var %s %s' % (logvar, val))
				self.sleep(self.throttle)
		return True

class qteyelink_log(eyelink_log, qtplugin.qtplugin):

	"""GUI part of the plug-in"""

	def __init__(self, name, experiment, string=None):

		"""
		Constructor

		Arguments:
		name		--	item name
		experiment	--	an experiment object

		Keyword arguments:
		string		--	a definitional string (default=None)
		"""
		
		eyelink_log.__init__(self, name, experiment, string)
		qtplugin.qtplugin.__init__(self, __file__)

	def init_edit_widget(self):

		"""Initialize the controls"""

		self.lock = True
		qtplugin.qtplugin.init_edit_widget(self, False)
		self.add_spinbox_control('throttle', \
			'Sleep time between messages', 0, 1000, suffix='ms', tooltip= \
			'A sleep time between messages to avoid overloading the EyeLink and losing data')
		self.add_checkbox_control('auto_log', \
			'Auto-detect and log all variables', tooltip= \
			'Automatically auto-detect and log variables')
		self.add_editor_control("msg", "Log message", tooltip= \
			"The message to write to the Eyelink")
		self.lock = True

	def apply_edit_changes(self):

		"""Apply the controls"""

		if not qtplugin.qtplugin.apply_edit_changes(self, False) or self.lock:
			return
		self.experiment.main_window.refresh(self.name)

	def edit_widget(self):

		"""Update the controls"""

		self.lock = True
		qtplugin.qtplugin.edit_widget(self)
		self.lock = False
		return self._edit_widget
