import sys

from scriptutils import logger
from scriptutils.userinput import SelectFromList
from revitutils import doc, Action, ActionGroup

# noinspection PyUnresolvedReferences
import clr
# noinspection PyUnresolvedReferences
from Autodesk.Revit.DB import FilteredElementCollector as Fec
# noinspection PyUnresolvedReferences
from Autodesk.Revit.DB import Element, ElementType, TransactionGroup, Transaction, Viewport
# noinspection PyUnresolvedReferences
from Autodesk.Revit.UI import TaskDialog


__doc__ = 'Asks user to select the viewport types to be purged and the viewport type to be replaced with ' \
          'and purges the viewport types. I made this tool to fix a problem with viewport types duplicating '\
          'themselves into unpurgable types.'


class ViewPortType:
    def __init__(self, rvt_element_type):
        self._rvt_type = rvt_element_type

    def __str__(self):
        return Element.Name.GetValue(self._rvt_type)

    def __repr__(self):
        return '<%s Name:%s Id:%d>' % (self.__class__.__name__,
                                       Element.Name.GetValue(self._rvt_type), self._rvt_type.Id.IntegerValue)

    def __lt__(self, other):
        return str(self) < str(other)

    @property
    def name(self):
        return str(self)

    def get_rvt_obj(self):
        return self._rvt_type

    def find_linked_elements(self):
        t = Transaction(doc, "Search for linked elements")
        t.Start()
        linked_element_ids = doc.Delete(self._rvt_type.Id)
        t.RollBack()

        return linked_element_ids


# Collect viewport types -----------------------------------------------------------------------------------------------
all_element_types = Fec(doc).OfClass(clr.GetClrType(ElementType)).ToElements()
all_viewport_types = [ViewPortType(x) for x in all_element_types if x.FamilyName == 'Viewport']

logger.debug('Viewport types: {}'.format(all_viewport_types))

# Ask user for viewport types to be purged -----------------------------------------------------------------------------
purge_vp_types = SelectFromList.show(sorted(all_viewport_types), title='Select Types to be Converted')

if not purge_vp_types:
    sys.exit()

for purged_vp_type in purge_vp_types:
    logger.debug('Viewport type to be purged: {}'.format(repr(purged_vp_type)))

# Ask user for replacement viewport type -------------------------------------------------------------------------------
dest_vp_types = SelectFromList.show(sorted([x for x in all_viewport_types if x not in purge_vp_types]),
                                   multiselect=False,  title='Select Replacement Type')

if len(dest_vp_types) >= 1:
    dest_vp_typeid = dest_vp_types[0].get_rvt_obj().Id
else:
    sys.exit()


# Collect all elements that are somehow linked to the viewport types to be purged --------------------------------------
TaskDialog.Show('pyRevit', 'Starting Conversion. Hit Cancel if you get any prompts.')

purge_dict = {}
for purge_vp_type in purge_vp_types:
    logger.info('Finding all viewports of type: {}'.format(purge_vp_type.name))
    logger.debug('Purging: {}'.format(repr(purge_vp_type)))
    linked_elements = purge_vp_type.find_linked_elements()
    logger.debug('{} elements are linked to this viewport type.'.format(len(linked_elements)))
    purge_dict[purge_vp_type.name] = linked_elements


# Perform cleanup ------------------------------------------------------------------------------------------------------
tg = TransactionGroup(doc, 'Fixed Unpurgable Viewport Types')
tg.Start()


# TRANSACTION 1
# Correct all existing viewports that use the viewport types to be purged
# Collect viewports and find the ones that use the purging viewport types
all_viewports = Fec(doc).OfClass(clr.GetClrType(Viewport)).ToElements()
purge_vp_ids = [x.get_rvt_obj().Id for x in purge_vp_types]
t1 = Transaction(doc, 'Correct Viewport Types')
t1.Start()
for vp in all_viewports:
    if vp.GetTypeId() in purge_vp_ids:
        try:
            # change their type to the destination type
            logger.debug('Changing viewport type for viewport with id: {}'.format(vp.Id))
            vp.ChangeTypeId(dest_vp_typeid)
        except Exception as change_err:
            logger.debug('Can not change type for viewport with id: {} | {}'.format(vp.Id, change_err))
t1.Commit()


# TRANSACTION 2
# Correct all hidden viewport elements that use the viewport types to be purged
t2 = Transaction(doc, 'Correct Hidden Viewport Types')
t2.Start()
for vp_type_name, linked_elements in purge_dict.items():
    has_error = False
    logger.info('Converting all viewports of type: {}'.format(vp_type_name))
    for linked_elid in linked_elements:
        linked_el = doc.GetElement(linked_elid)
        try:
            if isinstance(linked_el, Viewport) and linked_el.GetTypeId() in purge_vp_ids:
                logger.debug('Changing viewport type for hidden viewport with id: {}'.format(linked_el.Id))
                linked_el.ChangeTypeId(dest_vp_typeid)
        except Exception as change_err:
            has_error = True
            logger.debug('Can not change type for hidden viewport with id: {} | {}'.format(linked_el.Id, change_err))
    if has_error:
        logger.warning('Exceptions occured while converting viewport type: {}\n' \
                       'This is minor and the type might still be purgable.'.format(vp_type_name))

t2.Commit()


# # TRANSACTION 3
# # Now remove the viewport types to be purged
# for vp_type in purge_vp_types:
#     logger.debug('Removing viewport type: {}'.format(vp_type))
#     t3 = Transaction(doc, 'Remove viewport type')
#     t3.Start()
#     try:
#         doc.Delete(vp_type.get_rvt_obj().Id)
#         t3.Commit()
#     except:
#         logger.error('Can not remove: {}'.format(vp_type))
#         t3.RollBack()
#

tg.Commit()

TaskDialog.Show('pyRevit', 'Conversion Completed.\nRemove the unused viewport types using Purge tool.')
