"""Offline checks of the real register -> on-disk Sources HTML -> credit reader."""
import pytest

from scripts import build_sources_register as register
from scripts.relief.source_credit_check import CreditCheck, check
from tests.unit.test_sources_register import add_contours, add_relief_pointer, make_root, region, row


NAME = 'Fixture & Partners <Grid>'
ATTRIBUTION = '© Fixture & Partners, "Survey"'
SHADING = 'Depth shading'
CONTOURS = 'Depth contours'


def grid(ident='shade-grid', *, name=NAME, attribution=ATTRIBUTION, **kwargs):
    result = row(ident, name, **kwargs)
    result['rights']['attribution'] = attribution
    return result


def write_page(root):
    _, fresh, _ = register.build(root)
    page = root / register.PAGE
    page.write_text(fresh, encoding='utf-8')
    return page


@pytest.fixture
def reviewed(tmp_path):
    root = make_root(tmp_path, [grid(), grid('contour-grid', attribution='Other survey credit')],
                     [region('r1', 'Fixture Bay'), region('r2', 'Fixture Bay')])
    add_relief_pointer(root, ('shade-grid',))
    return root


def test_escaped_register_credit_in_its_region_is_present_and_read_only(reviewed):
    """Decode visible markup and use catalogue fields, not pointer-only labels or serialized HTML."""
    add_contours(reviewed, region_id='r1')
    page = write_page(reviewed)
    original = page.read_text(encoding='utf-8')
    reflowed = original.replace('Fixture &amp; Partners &lt;Grid&gt;</strong>',
                                'Fixture <em>&amp; Partners</em> &lt;Grid&gt;</strong>')
    reflowed = reflowed.replace('Source page</a></li>', 'Source page</a>\n</li>')
    assert reflowed != original
    page.write_text(reflowed, encoding='utf-8')
    assert set(check(reviewed)) == {
        CreditCheck('r1', SHADING, 'shade-grid', 'present'),
        CreditCheck('r1', CONTOURS, 'contour-grid', 'present'),
        CreditCheck('r2', SHADING, None, 'no-reviewed-pointer'),
    }
    assert page.read_text(encoding='utf-8') == reflowed


def test_credit_present_only_under_same_named_wrong_region_is_missing(reviewed):
    """A global search or joining by region display name would wrongly accept the relocated credit."""
    add_contours(reviewed, region_id='r2')
    path = write_page(reviewed)
    page = path.read_text(encoding='utf-8')
    left, layer, right = page.partition('<h5>Depth shading</h5>')
    assert layer and 'id="region-r1"' in left and 'id="region-r2"' in right
    shading_rows, end_list, rest = right.partition('</ul>')
    assert end_list and 'Credit: © Fixture &amp; Partners, &quot;Survey&quot;' in shading_rows
    wrong_region = rest.replace('<h5>Depth contours</h5>', layer + shading_rows + end_list + '\n<h5>Depth contours</h5>', 1)
    path.write_text(left + wrong_region, encoding='utf-8')
    assert set(check(reviewed)) == {
        CreditCheck('r1', SHADING, 'shade-grid', 'missing-credit'),
        CreditCheck('r2', SHADING, None, 'no-reviewed-pointer'),
        CreditCheck('r2', CONTOURS, 'contour-grid', 'present'),
    }


def test_credit_in_right_region_but_wrong_layer_is_missing(reviewed):
    """An anchor-only check would accept a shading credit relabelled as contours."""
    path = write_page(reviewed)
    page = path.read_text(encoding='utf-8')
    path.write_text(page.replace('<h5>Depth shading</h5>', '<h5>Depth contours</h5>'), encoding='utf-8')
    assert CreditCheck('r1', SHADING, 'shade-grid', 'missing-credit') in check(reviewed)


@pytest.mark.parametrize('replacement', [
    pytest.param('Credit: Some other attribution ·', id='wrong-attribution'),
    pytest.param('<!-- Credit: © Fixture &amp; Partners, &quot;Survey&quot; · -->', id='comment-only'),
    pytest.param('<span hidden>Credit: © Fixture &amp; Partners, &quot;Survey&quot; · </span>', id='hidden-text'),
    pytest.param('<span style="display:none">Credit: © Fixture &amp; Partners, &quot;Survey&quot; · </span>', id='display-none'),
    pytest.param('<span style="display:none/**/">Credit: © Fixture &amp; Partners, &quot;Survey&quot; · </span>', id='display-none-comment'),
    pytest.param('<span style="display/**/:/**/none/**/!/**/important">Credit: © Fixture &amp; Partners, &quot;Survey&quot; · </span>', id='display-none-comments-throughout'),
    pytest.param('<span style="color: red; DISPLAY : none !important"><em>Credit: © Fixture &amp; Partners, &quot;Survey&quot; · </em></span>', id='display-none-nested'),
    pytest.param('</li><li>Credit: © Fixture &amp; Partners, &quot;Survey&quot; ·', id='separate-item'),
])
def test_name_and_visible_attribution_must_share_the_same_entry(reviewed, replacement):
    """A name-only, raw-text or list-wide check could mistake decoy attribution for this item's credit."""
    path = write_page(reviewed)
    page = path.read_text(encoding='utf-8')
    credit = 'Credit: © Fixture &amp; Partners, &quot;Survey&quot; ·'
    assert page.count(credit) == 1
    path.write_text(page.replace(credit, replacement), encoding='utf-8')
    assert CreditCheck('r1', SHADING, 'shade-grid', 'missing-credit') in check(reviewed)


def test_no_reviewed_pointer_is_not_missing_credit(tmp_path):
    """A source eligible for display must not be mistaken for a reviewed pointer."""
    root = make_root(tmp_path, [grid()], [region('r1', 'Fixture Bay')])
    write_page(root)
    assert check(root) == (CreditCheck('r1', SHADING, None, 'no-reviewed-pointer'),)


def test_repeated_identical_display_tuple_cannot_prove_distinct_ids(tmp_path):
    """Counting indistinguishable entries would certify IDs that are never exposed by HTML."""
    root = make_root(tmp_path, [grid('a-grid'), grid('b-grid')], [region('r1', 'Fixture Bay')])
    add_relief_pointer(root, ('a-grid', 'b-grid'))
    page = write_page(root).read_text(encoding='utf-8')
    assert page.count('<strong>Fixture &amp; Partners &lt;Grid&gt;</strong>') == 2
    assert check(root) == (
        CreditCheck('r1', SHADING, 'a-grid', 'unresolvable-display-tuple'),
        CreditCheck('r1', SHADING, 'b-grid', 'unresolvable-display-tuple'),
    )


def test_legacy_row_without_attribution_has_no_display_tuple(tmp_path):
    """A legacy listable row with no credit is unresolvable, not a missing render of a known tuple."""
    root = make_root(tmp_path, [grid(attribution='', display=None)], [region('r1', 'Fixture Bay')])
    add_relief_pointer(root, ('shade-grid',))
    write_page(root)
    assert check(root) == (CreditCheck('r1', SHADING, 'shade-grid', 'unresolvable-display-tuple'),)
