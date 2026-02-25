- string:
    name: 'GERRIT_BRANCH'
    default: '{version|master}'
- string:
    name: 'GERRIT_PROJECT'
    default: '{review_project|}'
- string:
    name: 'GERRIT_REFSPEC'
    default: ''
    description: 'The refspec to fetch. E.g. `refs/changes/15/14715/2`. You may find it in the gerrit interface for downloading a specific revision of patch'
- string:
    name: 'GERRIT_NAME'
    default: 'review.lttng.org'
- string:
    name: 'GERRIT_HOST'
    default: 'review.lttng.org'
