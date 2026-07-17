# -*- coding: utf-8 -*-

from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

    def has_group(self, group_ext_id=None, *args, **kwargs):
        """
        Odoo 19 POS/Restaurant compatibility guard.

        Some frontend calls res.users.has_group through RPC with:
        - no real user recordset: res.users()
        - extra positional args
        - sometimes user_id first, group xml id second

        Odoo's original has_group() requires one user record, so we normalize
        the call and then call the original method on a real user.
        """

        user = self if len(self) == 1 else self.env.user
        group_xmlid = group_ext_id or kwargs.get('group_ext_id')

        # Case: first argument is user_id, second argument is group xml id
        if isinstance(group_xmlid, int):
            candidate_user = self.browse(group_xmlid).exists()
            if candidate_user:
                user = candidate_user
            group_xmlid = None

        # Look inside extra args for user_id and group xml id
        for arg in args:
            if isinstance(arg, str) and arg:
                group_xmlid = arg
            elif isinstance(arg, int):
                candidate_user = self.browse(arg).exists()
                if candidate_user:
                    user = candidate_user

        # Optional kwargs user id
        user_id = kwargs.get('user_id')
        if isinstance(user_id, int):
            candidate_user = self.browse(user_id).exists()
            if candidate_user:
                user = candidate_user

        if not group_xmlid or not isinstance(group_xmlid, str):
            return False

        if len(user) != 1:
            user = self.env.user

        # Important: call parent with ONLY the group xml id.
        # Do not pass *args to parent, because Odoo 19 original method
        # accepts only one argument after self.
        return super(ResUsers, user).has_group(group_xmlid)