from __future__ import absolute_import, unicode_literals
from rest_framework import status
from django.core.exceptions import ObjectDoesNotExist

from substrapp.models import DataManager
from substrapp.ledger_utils import invoke_ledger


def createLedgerDataManager(args, pkhash, sync=False):

    data, st = invoke_ledger(fcn='registerDataManager', args=args, sync=sync)

    try:
        instance = DataManager.objects.get(pk=pkhash)
    except ObjectDoesNotExist:
        pass
    else:
        # if not created on ledger, delete from local db
        if st not in (status.HTTP_201_CREATED, status.HTTP_408_REQUEST_TIMEOUT):
            instance.delete()
        else:
            # if created on ledger
            if st != status.HTTP_408_REQUEST_TIMEOUT:
                instance.validated = True
                instance.save()
                data['validated'] = True

    return data, st


def updateLedgerDataManager(args, sync=False):
    args = {
        'dataManagerKey': args[0],
        'objectiveKey': args[1],
    }
    return invoke_ledger(fcn='updateDataManager', args=args, sync=sync)
