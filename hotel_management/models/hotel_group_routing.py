def action_mass_group_checkin(self):
        for group in self:
            # SMARTER SEARCH: Grab all rooms that belong to this group, 
            # ignoring exact states, as long as they aren't already checked in or cancelled!
            reservations = self.env['hotel.reservation'].search([
                ('group_id', '=', group.id),
                ('state', 'not in', ['check_in', 'done', 'cancel']) 
            ])

            if not reservations:
                raise UserError(_("There are no pending reservations to check in for this group."))

            # Loop through and check them all in
            for res in reservations:
                res.write({
                    'billing_routing': group.billing_routing
                })
                
                if hasattr(res, 'action_checkin'):
                    res.action_checkin()
                else:
                    res.write({'state': 'check_in'})