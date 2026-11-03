from django.shortcuts import render

def home(request):
    """
    Landing / Dashboard view for Project Manager.
    """
    context = {
        'page_title': 'Dashboard Overview',
        'metrics': {
            'active_projects': 8,
            'pending_tasks': 24,
            'completed_tasks': 67,
            'team_members': 5,
        },
        'recent_projects': [
            {
                'name': 'Warehouse Inventory Audit',
                'category': 'Supply Chain Ops',
                'progress': 75,
                'status': 'In Progress',
                'status_class': 'success',
                'due_date': 'Nov 15, 2026',
            },
            {
                'name': 'Hardware Asset Tracking',
                'category': 'IT Infrastructure',
                'progress': 45,
                'status': 'In Progress',
                'status_class': 'warning',
                'due_date': 'Nov 28, 2026',
            },
            {
                'name': 'Supplier Integration API',
                'category': 'External Logistics',
                'progress': 90,
                'status': 'Review',
                'status_class': 'info',
                'due_date': 'Nov 10, 2026',
            },
            {
                'name': 'Quarterly Maintenance Schedule',
                'category': 'Facilities',
                'progress': 20,
                'status': 'Planning',
                'status_class': 'secondary',
                'due_date': 'Dec 05, 2026',
            },
        ],
        'upcoming_tasks': [
            {'title': 'Review sensory node telemetry report', 'project': 'Warehouse Audit', 'due': 'Tomorrow', 'priority': 'High', 'priority_class': 'danger'},
            {'title': 'Verify database replication status', 'project': 'IT Infrastructure', 'due': 'In 3 days', 'priority': 'Medium', 'priority_class': 'warning'},
            {'title': 'Update stock replenishment thresholds', 'project': 'Logistics', 'due': 'Nov 08', 'priority': 'Low', 'priority_class': 'info'},
            {'title': 'Sync user permissions with LDAP / DB groups', 'project': 'Security', 'due': 'Nov 12', 'priority': 'Medium', 'priority_class': 'warning'},
        ],
        'recent_activities': [
            {'user': 'Michael G.', 'action': 'updated milestone for Warehouse Audit', 'time': '15m ago', 'icon': 'bi-check2-circle', 'color': 'text-success'},
            {'user': 'System', 'action': 'completed daily database sync', 'time': '1h ago', 'icon': 'bi-database-check', 'color': 'text-primary'},
            {'user': 'Team Ops', 'action': 'assigned 3 new tasks to Inventory', 'time': '3h ago', 'icon': 'bi-list-task', 'color': 'text-warning'},
            {'user': 'Michael G.', 'action': 'logged in via local console', 'time': 'Today', 'icon': 'bi-shield-check', 'color': 'text-info'},
        ],
    }
    return render(request, 'home.html', context)
