# vc/services/vc_target_approval_service.py

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, asdict
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count, Avg, Max, Min, Sum, F, Value, Case, When
from django.db.models.functions import Coalesce
from django.utils import timezone

# Import models based on your existing code patterns
from hr.models import SupervisorPerformanceTarget
from spe.models import SPEPeriod
from users.models import CustomUser, Department, PerformanceTarget, StaffProfile

User = get_user_model()
logger = logging.getLogger(__name__)


@dataclass
class TargetStats:
    """Data class for target statistics"""
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    draft: int = 0
    total: int = 0
    completion_rate: float = 0.0
    pending_rate: float = 0.0
    avg_weight: float = 0.0
    avg_target_score: float = 0.0


@dataclass
class TargetFilter:
    """Data class for target filters"""
    department: Optional[str] = None
    target_type: str = 'all'  # 'all', 'supervisor', 'regular'
    search: str = ''
    status: str = 'pending'  # 'all', 'pending', 'approved', 'rejected'
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    staff_role: Optional[str] = None


class VCTargetApprovalService:
    """Service for VC to approve/reject performance targets for ALL staff types"""
    
    # ==================== PERMISSION & VALIDATION METHODS ====================
    
    @staticmethod
    def validate_vc_permission(user: User) -> Tuple[bool, Optional[str]]:
        """Validate that user has VC staff permissions"""
        if not user.is_authenticated:
            return False, "Authentication required"
        
        if not hasattr(user, 'is_vc_staff') or not user.is_vc_staff:
            return False, "Only Vice Chancellor staff can approve targets."
        
        if not user.is_active:
            return False, "User account is inactive."
        
        return True, None
    
    @staticmethod
    def validate_period() -> Tuple[Optional[SPEPeriod], Optional[str]]:
        """Validate and get active evaluation period"""
        try:
            period = SPEPeriod.objects.filter(is_active=True).first()
            if not period:
                return None, "No active evaluation period found. Please contact administrator."
            
            return period, None
            
        except Exception as e:
            logger.error(f"Error validating period: {str(e)}")
            return None, f"Error validating period: {str(e)}"
    
    @staticmethod
    def validate_target_for_approval(target: Any) -> Tuple[bool, Optional[str]]:
        """Validate if target can be approved"""
        if not target:
            return False, "Target not found"
        
        # Allow approval for both 'pending' and 'submitted' statuses
        if target.status not in ['pending', 'submitted']:
            return False, f"Target is already {target.get_status_display().lower()}"
        
        # Check if target has required fields
        if not target.description or not target.description.strip():
            return False, "Target description is required"
        
        # Only validate weight for PerformanceTarget, not SupervisorPerformanceTarget
        if hasattr(target, 'staff'):  # This is a PerformanceTarget
            if hasattr(target, 'weight') and (target.weight is None or target.weight <= 0):
                return False, "Target weight must be greater than 0"
        
        # Check if success measures exist (if field exists)
        if hasattr(target, 'success_measures'):
            if not target.success_measures or not target.success_measures.strip():
                return False, "Success measures are required for approval"
        
        return True, None
    
    # ==================== TARGET RETRIEVAL METHODS ====================
    
    @staticmethod
    def get_target_model(staff: CustomUser) -> str:
        """Determine which target model to use based on staff role"""
        if staff.role == 'supervisor':
            return 'SupervisorPerformanceTarget'
        else:
            return 'PerformanceTarget'
    
    @staticmethod
    def get_target_queryset(staff: CustomUser, period: SPEPeriod) -> Any:
        """Get the appropriate queryset based on staff role"""
        if staff.role == 'supervisor':
            return SupervisorPerformanceTarget.objects.filter(
                supervisor=staff, period=period
            ).select_related('supervisor', 'period')
        else:
            return PerformanceTarget.objects.filter(
                staff=staff, period=period
            ).select_related('staff', 'period')
    
    @staticmethod
    def get_target_by_id(target_model: str, target_id: int) -> Tuple[Optional[Any], Optional[str]]:
        """Get a specific target by ID with detailed select_related"""
        try:
            if target_model == 'SupervisorPerformanceTarget':
                target = SupervisorPerformanceTarget.objects.select_related(
                    'supervisor', 
                    'supervisor__department',
                    'period',
                ).get(id=target_id)
            elif target_model == 'PerformanceTarget':
                target = PerformanceTarget.objects.select_related(
                    'staff',
                    'staff__department',
                    'period',
                ).get(id=target_id)
            else:
                return None, "Invalid target model"
            
            return target, None
            
        except (SupervisorPerformanceTarget.DoesNotExist, PerformanceTarget.DoesNotExist):
            return None, "Target not found"
        except Exception as e:
            logger.error(f"Error getting target: {str(e)}", exc_info=True)
            return None, f"Error retrieving target: {str(e)}"
    
    @staticmethod
    def get_target_details(target_model: str, target_id: int) -> Dict:
        """Get detailed information about a target including related data"""
        target, error = VCTargetApprovalService.get_target_by_id(target_model, target_id)
        
        if error:
            return {"success": False, "error": error}
        
        # Determine staff based on target type
        if target_model == 'SupervisorPerformanceTarget':
            staff = target.supervisor
            staff_role = 'Supervisor'
            staff_designation = 'Supervisor'
            other_targets = SupervisorPerformanceTarget.objects.filter(
                supervisor=staff,
                period=target.period
            ).exclude(id=target_id).select_related(
                'supervisor', 'period'
            ).order_by('target_number')
            
        else:  # PerformanceTarget
            staff = target.staff
            staff_role = staff.get_role_display() if hasattr(staff, 'get_role_display') else staff.role
            other_targets = PerformanceTarget.objects.filter(
                staff=staff,
                period=target.period
            ).exclude(id=target_id).select_related(
                'staff', 'period'
            ).order_by('target_number')
        
        # Get staff profile
        try:
            staff_profile = StaffProfile.objects.get(user=staff)
            staff_designation = staff_profile.designation or 'Staff'
            staff_pf_number = staff_profile.pf_number or getattr(staff, 'pf_number', 'N/A')
        except StaffProfile.DoesNotExist:
            staff_profile = None
            staff_designation = staff.role.title()
            staff_pf_number = getattr(staff, 'pf_number', 'N/A')
        
        # Get target statistics for this staff
        target_stats = VCTargetApprovalService.get_staff_target_statistics(staff, target.period)
        
        # Get approval history if exists
        approval_history = VCTargetApprovalService.get_target_approval_history(target)
        
        return {
            "success": True,
            "target": target,
            "target_model": target_model,
            "staff": staff,
            "staff_profile": staff_profile,
            "staff_role": staff_role,
            "staff_designation": staff_designation,
            "staff_pf_number": staff_pf_number,
            "other_targets": other_targets,
            "target_stats": target_stats,
            "approval_history": approval_history,
            "active_period": target.period,
            "can_approve": target.status in ['pending', 'submitted'],  # FIXED: Allow both statuses
            "can_reject": target.status in ['pending', 'submitted'],  # FIXED: Allow both statuses
            "is_approved": target.status == 'approved',
            "is_rejected": target.status == 'rejected',
        }
    
    @staticmethod
    def get_target_approval_history(target: Any) -> List[Dict]:
        """Get approval history for a target"""
        history = []
        
        # Add creation event
        if hasattr(target, 'created_at') and target.created_at:
            history.append({
                'action': 'created',
                'by': target.created_by.get_full_name() if hasattr(target, 'created_by') and target.created_by else 'System',
                'date': target.created_at,
                'comments': 'Target created',
            })
        
        # Add submission event if exists
        if hasattr(target, 'submitted_at') and target.submitted_at:
            history.append({
                'action': 'submitted',
                'by': target.staff.get_full_name() if hasattr(target, 'staff') else 
                      target.supervisor.get_full_name() if hasattr(target, 'supervisor') else 'Unknown',
                'date': target.submitted_at,
                'comments': 'Target submitted for approval',
            })
        
        # Add approval event if approved
        if target.status == 'approved' and hasattr(target, 'approved_at') and target.approved_at:
            history.append({
                'action': 'approved',
                'by': target.approved_by.get_full_name() if target.approved_by else 'System',
                'date': target.approved_at,
                'comments': getattr(target, 'approval_comments', '') or 'Approved without comments',
            })
        
        # Add rejection event if rejected
        if target.status == 'rejected' and hasattr(target, 'rejected_at') and target.rejected_at:
            history.append({
                'action': 'rejected',
                'by': target.rejected_by.get_full_name() if target.rejected_by else 'System',
                'date': target.rejected_at,
                'comments': getattr(target, 'rejection_reason', '') or 
                           getattr(target, 'rejection_comments', '') or 
                           'Rejected without reason',
            })
        
        # Sort by date
        history.sort(key=lambda x: x['date'], reverse=True)
        
        return history
    
    # ==================== TARGET LISTING & FILTERING ====================
    
    @staticmethod
    def apply_filters(queryset: Any, filters: TargetFilter, target_type: str) -> Any:
        """Apply filters to queryset"""
        # Apply department filter
        if filters.department:
            if target_type == 'supervisor':
                queryset = queryset.filter(supervisor__department__name__icontains=filters.department)
            else:
                queryset = queryset.filter(staff__department__name__icontains=filters.department)
        
        # Apply status filter - FIXED: Handle 'pending' filter to include 'submitted'
        if filters.status != 'all':
            if filters.status == 'pending':
                # Include both 'pending' and 'submitted' when filtering for pending
                queryset = queryset.filter(Q(status='pending') | Q(status='submitted'))
            else:
                queryset = queryset.filter(status=filters.status)
        
        # Apply search filter
        if filters.search:
            search_query = filters.search
            if target_type == 'supervisor':
                queryset = queryset.filter(
                    Q(description__icontains=search_query) |
                    Q(supervisor__first_name__icontains=search_query) |
                    Q(supervisor__last_name__icontains=search_query) |
                    Q(supervisor__email__icontains=search_query)
                )
            else:
                queryset = queryset.filter(
                    Q(description__icontains=search_query) |
                    Q(staff__first_name__icontains=search_query) |
                    Q(staff__last_name__icontains=search_query) |
                    Q(staff__email__icontains=search_query)
                )
        
        # Apply date filters
        if filters.start_date:
            try:
                start_date = datetime.strptime(filters.start_date, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__date__gte=start_date)
            except ValueError:
                pass
        
        if filters.end_date:
            try:
                end_date = datetime.strptime(filters.end_date, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__date__lte=end_date)
            except ValueError:
                pass
        
        return queryset
    
    @staticmethod
    def get_pending_targets_list(filters: Dict = None, page: int = 1, page_size: int = 20) -> Dict:
        """Get paginated list of pending targets with advanced filtering"""
        try:
            filters_dict = filters or {}
            target_filter = TargetFilter(**filters_dict)
            
            # Get active period
            period, error = VCTargetApprovalService.validate_period()
            if error:
                return {"success": False, "error": error}
            
            # Get supervisor targets - FIXED: Include both 'pending' and 'submitted'
            supervisor_targets = SupervisorPerformanceTarget.objects.filter(
                period=period
            ).filter(Q(status='pending') | Q(status='submitted')).select_related(
                'supervisor', 
                'supervisor__department',
                'period'
            ).order_by('-created_at')
            
            # Get regular staff targets - FIXED: Include both 'pending' and 'submitted'
            regular_targets = PerformanceTarget.objects.filter(
                period=period
            ).filter(Q(status='pending') | Q(status='submitted')).select_related(
                'staff', 
                'staff__department',
                'period'
            ).order_by('-created_at')
            
            # Apply type filter
            if target_filter.target_type == 'supervisors':
                regular_targets = regular_targets.none()
            elif target_filter.target_type == 'regular':
                supervisor_targets = supervisor_targets.none()
            
            # Apply filters
            supervisor_targets = VCTargetApprovalService.apply_filters(
                supervisor_targets, target_filter, 'supervisor'
            )
            regular_targets = VCTargetApprovalService.apply_filters(
                regular_targets, target_filter, 'regular'
            )
            
            # Combine targets into a single list with metadata
            all_targets = []
            
            for target in supervisor_targets:
                # Check if weight field exists, otherwise use a default
                weight = getattr(target, 'weight', 0) if hasattr(target, 'weight') else 0
                success_measures = getattr(target, 'success_measures', '') or ''
                
                all_targets.append({
                    'id': target.id,
                    'target_number': getattr(target, 'target_number', ''),
                    'description': target.description,
                    'short_description': target.description[:100] + '...' if len(target.description) > 100 else target.description,
                    'success_measures': success_measures,
                    'short_measures': (success_measures[:80] + '...' if len(success_measures) > 80 else success_measures),
                    'weight': weight,
                    'created_at': target.created_at,
                    'submitted_at': getattr(target, 'submitted_at', target.created_at),
                    'staff': target.supervisor,
                    'staff_name': target.supervisor.get_full_name(),
                    'staff_role': 'Supervisor',
                    'staff_role_code': 'supervisor',
                    'department': target.supervisor.department.name if target.supervisor.department else 'N/A',
                    'department_id': target.supervisor.department.id if target.supervisor.department else None,
                    'target_type': 'supervisor',
                    'target_model': 'SupervisorPerformanceTarget',
                    'period': target.period,
                    'status': target.status,
                    'status_display': target.get_status_display() if hasattr(target, 'get_status_display') else target.status,
                    'has_pf_number': hasattr(target.supervisor, 'pf_number') and target.supervisor.pf_number,
                    'pf_number': getattr(target.supervisor, 'pf_number', 'N/A'),
                    'email': target.supervisor.email,
                    'days_since_creation': (timezone.now().date() - target.created_at.date()).days if target.created_at else None,
                    'is_overdue': (timezone.now().date() - target.created_at.date()).days > 7 if target.created_at else False,
                })
            
            for target in regular_targets:
                staff_role = target.staff.get_role_display() if hasattr(target.staff, 'get_role_display') else target.staff.role
                
                # Check if weight field exists, otherwise use a default
                weight = getattr(target, 'weight', 0) if hasattr(target, 'weight') else 0
                success_measures = getattr(target, 'success_measures', '') or ''
                
                all_targets.append({
                    'id': target.id,
                    'target_number': getattr(target, 'target_number', ''),
                    'description': target.description,
                    'short_description': target.description[:100] + '...' if len(target.description) > 100 else target.description,
                    'success_measures': success_measures,
                    'short_measures': (success_measures[:80] + '...' if len(success_measures) > 80 else success_measures),
                    'weight': weight,
                    'created_at': target.created_at,
                    'submitted_at': getattr(target, 'submitted_at', target.created_at),
                    'staff': target.staff,
                    'staff_name': target.staff.get_full_name(),
                    'staff_role': staff_role,
                    'staff_role_code': target.staff.role,
                    'department': target.staff.department.name if target.staff.department else 'N/A',
                    'department_id': target.staff.department.id if target.staff.department else None,
                    'target_type': 'regular',
                    'target_model': 'PerformanceTarget',
                    'period': target.period,
                    'status': target.status,
                    'status_display': target.get_status_display() if hasattr(target, 'get_status_display') else target.status,
                    'has_pf_number': hasattr(target.staff, 'pf_number') and target.staff.pf_number,
                    'pf_number': getattr(target.staff, 'pf_number', 'N/A'),
                    'email': target.staff.email,
                    'days_since_creation': (timezone.now().date() - target.created_at.date()).days if target.created_at else None,
                    'is_overdue': (timezone.now().date() - target.created_at.date()).days > 7 if target.created_at else False,
                })
            
            # Sort by submission date (newest first)
            all_targets.sort(key=lambda x: x['submitted_at'] or x['created_at'], reverse=True)
            
            # Pagination
            paginator = Paginator(all_targets, page_size)
            page_obj = paginator.get_page(page)
            
            # Get departments for filter dropdown
            departments = Department.objects.all().order_by('name')
            
            # Get status counts
            status_counts = {
                'pending': len(all_targets),
                'total_supervisor': len([t for t in all_targets if t['target_type'] == 'supervisor']),
                'total_regular': len([t for t in all_targets if t['target_type'] == 'regular']),
            }
            
            return {
                "success": True,
                "targets": all_targets,
                "page_obj": page_obj,
                "total_count": paginator.count,
                "total_pages": paginator.num_pages,
                "departments": departments,
                "active_period": period,
                "status_counts": status_counts,
                "filters": asdict(target_filter),
            }
            
        except Exception as e:
            logger.error(f"Error getting pending targets: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Error retrieving targets: {str(e)}"}
    
    # ==================== STATISTICS & ANALYTICS ====================
    
    @staticmethod
    def get_target_summary_stats(filters: Dict = None) -> Dict:
        """Get comprehensive summary statistics for targets"""
        try:
            filters_dict = filters or {}
            target_filter = TargetFilter(**filters_dict)
            
            period, error = VCTargetApprovalService.validate_period()
            if error:
                return {"success": False, "error": error}
            
            # Initialize base querysets
            supervisor_targets = SupervisorPerformanceTarget.objects.filter(
                period=period
            ).select_related('supervisor', 'supervisor__department')
            
            regular_targets = PerformanceTarget.objects.filter(
                period=period
            ).select_related('staff', 'staff__department')
            
            # Apply filters
            if target_filter.department:
                supervisor_targets = supervisor_targets.filter(
                    supervisor__department__name__icontains=target_filter.department
                )
                regular_targets = regular_targets.filter(
                    staff__department__name__icontains=target_filter.department
                )
            
            if target_filter.status != 'all':
                if target_filter.status == 'pending':
                    # Include both 'pending' and 'submitted' for pending filter
                    supervisor_targets = supervisor_targets.filter(Q(status='pending') | Q(status='submitted'))
                    regular_targets = regular_targets.filter(Q(status='pending') | Q(status='submitted'))
                else:
                    supervisor_targets = supervisor_targets.filter(status=target_filter.status)
                    regular_targets = regular_targets.filter(status=target_filter.status)
            
            # Calculate comprehensive statistics - handle missing fields
            supervisor_stats = supervisor_targets.aggregate(
                total=Count('id'),
                pending=Count('id', filter=Q(status='pending') | Q(status='submitted')),  # FIXED
                approved=Count('id', filter=Q(status='approved')),
                rejected=Count('id', filter=Q(status='rejected')),
                draft=Count('id', filter=Q(status='draft')),
            )
            
            # Check if performance_rating field exists
            if hasattr(SupervisorPerformanceTarget.objects.first(), 'performance_rating'):
                supervisor_stats['avg_score'] = supervisor_targets.aggregate(
                    avg_score=Avg('performance_rating')
                )['avg_score']
            else:
                supervisor_stats['avg_score'] = 0
            
            # Check if weight field exists
            supervisor_stats['avg_weight'] = 0
            supervisor_stats['total_weight'] = 0
            sample_supervisor = supervisor_targets.first()
            if sample_supervisor and hasattr(sample_supervisor, 'weight'):
                weight_stats = supervisor_targets.aggregate(
                    avg_weight=Avg('weight'),
                    total_weight=Sum('weight')
                )
                supervisor_stats['avg_weight'] = weight_stats['avg_weight'] or 0
                supervisor_stats['total_weight'] = weight_stats['total_weight'] or 0
            
            regular_stats = regular_targets.aggregate(
                total=Count('id'),
                pending=Count('id', filter=Q(status='pending') | Q(status='submitted')),  # FIXED
                approved=Count('id', filter=Q(status='approved')),
                rejected=Count('id', filter=Q(status='rejected')),
                draft=Count('id', filter=Q(status='draft')),
            )
            
            # Check if performance_rating field exists
            if hasattr(PerformanceTarget.objects.first(), 'performance_rating'):
                regular_stats['avg_score'] = regular_targets.aggregate(
                    avg_score=Avg('performance_rating')
                )['avg_score']
            else:
                regular_stats['avg_score'] = 0
            
            # Check if weight field exists
            regular_stats['avg_weight'] = 0
            regular_stats['total_weight'] = 0
            sample_regular = regular_targets.first()
            if sample_regular and hasattr(sample_regular, 'weight'):
                weight_stats = regular_targets.aggregate(
                    avg_weight=Avg('weight'),
                    total_weight=Sum('weight')
                )
                regular_stats['avg_weight'] = weight_stats['avg_weight'] or 0
                regular_stats['total_weight'] = weight_stats['total_weight'] or 0
            
            # Calculate combined totals with safe defaults
            total_targets = (supervisor_stats.get('total') or 0) + (regular_stats.get('total') or 0)
            total_pending = (supervisor_stats.get('pending') or 0) + (regular_stats.get('pending') or 0)
            total_approved = (supervisor_stats.get('approved') or 0) + (regular_stats.get('approved') or 0)
            total_rejected = (supervisor_stats.get('rejected') or 0) + (regular_stats.get('rejected') or 0)
            total_draft = (supervisor_stats.get('draft') or 0) + (regular_stats.get('draft') or 0)
            
            # Calculate rates
            approval_rate = (total_approved / total_targets * 100) if total_targets > 0 else 0
            pending_rate = (total_pending / total_targets * 100) if total_targets > 0 else 0
            
            # Calculate average weight
            supervisor_avg_weight = supervisor_stats.get('avg_weight') or 0
            regular_avg_weight = regular_stats.get('avg_weight') or 0
            avg_weight = 0
            
            if supervisor_avg_weight > 0 and regular_avg_weight > 0:
                avg_weight = (supervisor_avg_weight + regular_avg_weight) / 2
            elif supervisor_avg_weight > 0:
                avg_weight = supervisor_avg_weight
            elif regular_avg_weight > 0:
                avg_weight = regular_avg_weight
            
            # Calculate average score
            supervisor_avg_score = supervisor_stats.get('avg_score') or 0
            regular_avg_score = regular_stats.get('avg_score') or 0
            avg_target_score = 0
            
            if supervisor_avg_score > 0 and regular_avg_score > 0:
                avg_target_score = (supervisor_avg_score + regular_avg_score) / 2
            elif supervisor_avg_score > 0:
                avg_target_score = supervisor_avg_score
            elif regular_avg_score > 0:
                avg_target_score = regular_avg_score
            
            # Create comprehensive stats object
            stats = TargetStats(
                pending=total_pending,
                approved=total_approved,
                rejected=total_rejected,
                draft=total_draft,
                total=total_targets,
                completion_rate=round(approval_rate, 1),
                pending_rate=round(pending_rate, 1),
                avg_weight=round(avg_weight, 1),
                avg_target_score=round(avg_target_score, 1),
            )
            
            return {
                "success": True,
                "stats": asdict(stats),
                "supervisor_stats": supervisor_stats,
                "regular_stats": regular_stats,
                "period": period.name,
                "period_id": period.id,
            }
            
        except Exception as e:
            logger.error(f"Error getting summary stats: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Error calculating statistics: {str(e)}"}
    
    @staticmethod
    def get_staff_target_statistics(staff: CustomUser, period: SPEPeriod) -> Dict:
        """Get comprehensive statistics for all targets of a staff member"""
        try:
            if staff.role == 'supervisor':
                targets = SupervisorPerformanceTarget.objects.filter(
                    supervisor=staff, period=period
                )
            else:
                targets = PerformanceTarget.objects.filter(
                    staff=staff, period=period
                )
            
            # Calculate aggregate statistics - FIXED: Count BOTH pending and submitted
            stats = targets.aggregate(
                total_targets=Count('id'),
                pending_targets=Count('id', filter=Q(status='pending') | Q(status='submitted')),  # FIXED
                approved_targets=Count('id', filter=Q(status='approved')),
                rejected_targets=Count('id', filter=Q(status='rejected')),
                draft_targets=Count('id', filter=Q(status='draft')),
            )
            
            # Check for evaluated_targets field
            if hasattr(targets.first(), 'performance_rating'):
                stats['evaluated_targets'] = targets.filter(
                    performance_rating__isnull=False
                ).count()
                stats['avg_score'] = targets.aggregate(
                    Avg('performance_rating')
                )['performance_rating__avg'] or 0
            else:
                stats['evaluated_targets'] = 0
                stats['avg_score'] = 0
            
            # Check for weight field
            if hasattr(targets.first(), 'weight'):
                stats['total_weight'] = targets.aggregate(Sum('weight'))['weight__sum'] or 0
                stats['avg_weight'] = targets.aggregate(Avg('weight'))['weight__avg'] or 0
            else:
                stats['total_weight'] = 0
                stats['avg_weight'] = 0
            
            # Calculate completion rate
            total_targets = stats['total_targets'] or 0
            approved_targets = stats['approved_targets'] or 0
            
            completion_rate = (approved_targets / total_targets * 100) if total_targets > 0 else 0
            
            # Calculate evaluation rate
            evaluated_targets = stats['evaluated_targets'] or 0
            evaluation_rate = (evaluated_targets / total_targets * 100) if total_targets > 0 else 0
            
            return {
                'total_targets': total_targets,
                'pending_targets': stats['pending_targets'] or 0,
                'approved_targets': approved_targets,
                'rejected_targets': stats['rejected_targets'] or 0,
                'draft_targets': stats['draft_targets'] or 0,
                'evaluated_targets': evaluated_targets,
                'completion_rate': round(completion_rate, 1),
                'evaluation_rate': round(evaluation_rate, 1),
                'total_weight': stats['total_weight'],
                'avg_weight': round(stats['avg_weight'], 1),
                'avg_score': round(stats['avg_score'], 1),
                'has_incomplete_targets': (stats['pending_targets'] or 0) > 0 or (stats['draft_targets'] or 0) > 0,
                'is_fully_approved': approved_targets == total_targets and total_targets > 0,
            }
            
        except Exception as e:
            logger.error(f"Error getting staff target statistics: {str(e)}")
            return {
                'total_targets': 0,
                'pending_targets': 0,
                'approved_targets': 0,
                'rejected_targets': 0,
                'draft_targets': 0,
                'evaluated_targets': 0,
                'completion_rate': 0,
                'evaluation_rate': 0,
                'total_weight': 0,
                'avg_weight': 0,
                'avg_score': 0,
                'has_incomplete_targets': False,
                'is_fully_approved': False,
            }
    
    # ==================== APPROVAL/REJECTION METHODS ====================
    
    @staticmethod
    def approve_target(target_model: str, target_id: int, vc_user: User, comments: str = "") -> Dict:
        """Approve a target with comprehensive validation and logging"""
        try:
            with transaction.atomic():
                # Get the target
                target, error = VCTargetApprovalService.get_target_by_id(target_model, target_id)
                if error:
                    return {"success": False, "error": error}
                
                # Validate target for approval - FIXED: Allow both 'pending' and 'submitted'
                valid, validation_error = VCTargetApprovalService.validate_target_for_approval(target)
                if not valid:
                    return {"success": False, "error": validation_error}
                
                # Validate VC permission
                valid, perm_error = VCTargetApprovalService.validate_vc_permission(vc_user)
                if not valid:
                    return {"success": False, "error": perm_error}
                
                # Update target
                target.status = 'approved'
                if hasattr(target, 'approved_by'):
                    target.approved_by = vc_user
                if hasattr(target, 'approved_at'):
                    target.approved_at = timezone.now()
                if hasattr(target, 'approval_comments'):
                    target.approval_comments = comments
                
                # Set additional fields if they exist
                additional_fields = {
                    'approval_reason': comments,
                    'review_comments': comments,
                    'approval_notes': comments,
                    'vc_comments': comments,
                }
                
                for field_name, value in additional_fields.items():
                    if hasattr(target, field_name):
                        setattr(target, field_name, value)
                
                target.save()
                
                # Log the approval
                logger.info(
                    f"Target approved - ID: {target.id}, "
                    f"Number: {getattr(target, 'target_number', 'N/A')}, "
                    f"Staff: {target.supervisor if hasattr(target, 'supervisor') else target.staff}, "
                    f"Approved by: {vc_user.get_full_name()}"
                )
                
                # Get staff information for response
                if target_model == 'SupervisorPerformanceTarget':
                    staff_name = target.supervisor.get_full_name()
                    staff_role = 'Supervisor'
                    staff_email = target.supervisor.email
                else:
                    staff_name = target.staff.get_full_name()
                    staff_role = target.staff.get_role_display() if hasattr(target.staff, 'get_role_display') else target.staff.role
                    staff_email = target.staff.email
                
                return {
                    "success": True,
                    "message": f"Target #{getattr(target, 'target_number', '')} approved successfully!",
                    "target_id": target.id,
                    "target_number": getattr(target, 'target_number', ''),
                    "staff_name": staff_name,
                    "staff_role": staff_role,
                    "staff_email": staff_email,
                    "approved_at": getattr(target, 'approved_at', timezone.now()),
                    "approved_by": vc_user.get_full_name(),
                    "comments": comments,
                }
                
        except Exception as e:
            logger.error(f"Error approving target: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Error approving target: {str(e)}"}
    
    @staticmethod
    def reject_target(target_model: str, target_id: int, vc_user: User, reason: str) -> Dict:
        """Reject a target with comprehensive validation and logging"""
        try:
            with transaction.atomic():
                # Get the target
                target, error = VCTargetApprovalService.get_target_by_id(target_model, target_id)
                if error:
                    return {"success": False, "error": error}
                
                # Validate target for rejection - FIXED: Allow both 'pending' and 'submitted'
                if target.status not in ['pending', 'submitted']:
                    return {"success": False, "error": f"Target is already {target.get_status_display().lower() if hasattr(target, 'get_status_display') else target.status}"}
                
                # Validate VC permission
                valid, perm_error = VCTargetApprovalService.validate_vc_permission(vc_user)
                if not valid:
                    return {"success": False, "error": perm_error}
                
                # Validate rejection reason
                if not reason or not reason.strip():
                    return {"success": False, "error": "Rejection reason is required"}
                
                # Update target
                target.status = 'rejected'
                if hasattr(target, 'rejected_by'):
                    target.rejected_by = vc_user
                if hasattr(target, 'rejected_at'):
                    target.rejected_at = timezone.now()
                
                # Set rejection reason based on available fields
                rejection_fields = {
                    'rejection_reason': reason,
                    'rejection_comments': reason,
                    'reject_reason': reason,
                    'reject_comments': reason,
                    'rejection_notes': reason,
                }
                
                field_set = False
                for field_name, value in rejection_fields.items():
                    if hasattr(target, field_name):
                        setattr(target, field_name, value)
                        field_set = True
                
                # If no specific rejection field exists, use a generic field
                if not field_set:
                    if hasattr(target, 'comments'):
                        target.comments = f"Rejected by VC: {reason}"
                    elif hasattr(target, 'notes'):
                        target.notes = f"Rejected by VC: {reason}"
                
                target.save()
                
                # Log the rejection
                logger.info(
                    f"Target rejected - ID: {target.id}, "
                    f"Number: {getattr(target, 'target_number', 'N/A')}, "
                    f"Staff: {target.supervisor if hasattr(target, 'supervisor') else target.staff}, "
                    f"Rejected by: {vc_user.get_full_name()}, "
                    f"Reason: {reason[:100]}"
                )
                
                # Get staff information for response
                if target_model == 'SupervisorPerformanceTarget':
                    staff_name = target.supervisor.get_full_name()
                    staff_role = 'Supervisor'
                    staff_email = target.supervisor.email
                else:
                    staff_name = target.staff.get_full_name()
                    staff_role = target.staff.get_role_display() if hasattr(target.staff, 'get_role_display') else target.staff.role
                    staff_email = target.staff.email
                
                return {
                    "success": True,
                    "message": f"Target #{getattr(target, 'target_number', '')} rejected.",
                    "target_id": target.id,
                    "target_number": getattr(target, 'target_number', ''),
                    "staff_name": staff_name,
                    "staff_role": staff_role,
                    "staff_email": staff_email,
                    "rejected_at": getattr(target, 'rejected_at', timezone.now()),
                    "rejected_by": vc_user.get_full_name(),
                    "reason": reason,
                }
                
        except Exception as e:
            logger.error(f"Error rejecting target: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Error rejecting target: {str(e)}"}
    
    @staticmethod
    def bulk_process_targets(vc_user: User, target_data: List[Dict], action: str, comments: str = "") -> Dict:
        """Process multiple targets in bulk with detailed reporting"""
        try:
            with transaction.atomic():
                results = {
                    "total": len(target_data),
                    "processed": 0,
                    "approved": 0,
                    "rejected": 0,
                    "failed": 0,
                    "skipped": 0,
                    "failed_details": [],
                    "success_details": []
                }
                
                for item in target_data:
                    target_model = item.get('target_model')
                    target_id = item.get('target_id')
                    
                    if not target_model or not target_id:
                        results["failed"] += 1
                        results["failed_details"].append({
                            "error": "Missing data",
                            "item": item,
                            "target_id": target_id,
                            "target_model": target_model
                        })
                        continue
                    
                    try:
                        if action == 'approve':
                            result = VCTargetApprovalService.approve_target(
                                target_model, target_id, vc_user, comments
                            )
                            
                            if result["success"]:
                                results["approved"] += 1
                                results["processed"] += 1
                                results["success_details"].append({
                                    "target_id": target_id,
                                    "target_number": result.get("target_number"),
                                    "staff_name": result.get("staff_name"),
                                    "message": result.get("message")
                                })
                            else:
                                results["failed"] += 1
                                results["failed_details"].append({
                                    "target_id": target_id,
                                    "target_model": target_model,
                                    "error": result.get("error", "Unknown error")
                                })
                                
                        elif action == 'reject':
                            # For bulk reject, use comments as reason
                            reason = comments or "Rejected in bulk action"
                            result = VCTargetApprovalService.reject_target(
                                target_model, target_id, vc_user, reason
                            )
                            
                            if result["success"]:
                                results["rejected"] += 1
                                results["processed"] += 1
                                results["success_details"].append({
                                    "target_id": target_id,
                                    "target_number": result.get("target_number"),
                                    "staff_name": result.get("staff_name"),
                                    "message": result.get("message")
                                })
                            else:
                                results["failed"] += 1
                                results["failed_details"].append({
                                    "target_id": target_id,
                                    "target_model": target_model,
                                    "error": result.get("error", "Unknown error")
                                })
                        
                        else:
                            results["failed"] += 1
                            results["failed_details"].append({
                                "target_id": target_id,
                                "target_model": target_model,
                                "error": f"Invalid action: {action}"
                            })
                            
                    except Exception as e:
                        results["failed"] += 1
                        results["failed_details"].append({
                            "target_id": target_id,
                            "target_model": target_model,
                            "error": str(e)
                        })
                
                # Prepare comprehensive summary message
                total_processed = results["approved"] + results["rejected"]
                action_text = "approved" if action == 'approve' else "rejected"
                
                if total_processed == 0 and results["failed"] == 0:
                    return {
                        "success": False,
                        "message": "No targets were processed.",
                        "results": results
                    }
                
                message = f"Bulk action completed: {total_processed} target(s) {action_text}"
                if results["approved"] > 0:
                    message += f" ({results['approved']} approved)"
                if results["rejected"] > 0:
                    message += f" ({results['rejected']} rejected)"
                if results["failed"] > 0:
                    message += f", {results['failed']} failed"
                
                # Log bulk action
                logger.info(
                    f"Bulk {action} completed by {vc_user.get_full_name()}: "
                    f"{results['approved']} approved, {results['rejected']} rejected, "
                    f"{results['failed']} failed"
                )
                
                return {
                    "success": True,
                    "message": message,
                    "results": results
                }
                
        except Exception as e:
            logger.error(f"Error in bulk processing: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Error processing bulk action: {str(e)}"}
    
    # ==================== STAFF-RELATED METHODS ====================
    
    @staticmethod
    def get_staff_with_pending_targets(filters: Dict = None) -> Dict:
        """Get comprehensive list of staff who have pending targets"""
        try:
            filters_dict = filters or {}
            target_filter = TargetFilter(**filters_dict)
            
            period, error = VCTargetApprovalService.validate_period()
            if error:
                return {"success": False, "error": error}
            
            # Get all staff with pending targets - FIXED: Include both 'pending' and 'submitted'
            staff_list = []
            
            # Check supervisor targets
            supervisor_targets = SupervisorPerformanceTarget.objects.filter(
                period=period
            ).filter(Q(status='pending') | Q(status='submitted')).select_related('supervisor', 'supervisor__department').values(
                'supervisor'
            ).annotate(
                pending_count=Count('id'),
                total_targets=Count('id', filter=Q(period=period)),
                oldest_pending=Min('created_at')
            )
            
            for item in supervisor_targets:
                try:
                    staff = CustomUser.objects.get(id=item['supervisor'])
                    
                    # Get staff profile
                    try:
                        profile = StaffProfile.objects.get(user=staff)
                        designation = profile.designation or 'Supervisor'
                        pf_number = profile.pf_number or getattr(staff, 'pf_number', 'N/A')
                    except StaffProfile.DoesNotExist:
                        designation = 'Supervisor'
                        pf_number = getattr(staff, 'pf_number', 'N/A')
                    
                    staff_list.append({
                        'staff': staff,
                        'staff_id': staff.id,
                        'staff_name': staff.get_full_name(),
                        'staff_role': 'Supervisor',
                        'staff_role_code': 'supervisor',
                        'department': staff.department.name if staff.department else 'N/A',
                        'department_id': staff.department.id if staff.department else None,
                        'designation': designation,
                        'pf_number': pf_number,
                        'email': staff.email,
                        'pending_count': item['pending_count'],
                        'total_targets': item['total_targets'],
                        'oldest_pending': item['oldest_pending'],
                        'days_pending': (timezone.now().date() - item['oldest_pending'].date()).days if item['oldest_pending'] else None,
                        'completion_rate': round(((item['total_targets'] - item['pending_count']) / item['total_targets'] * 100) if item['total_targets'] > 0 else 0, 1),
                        'target_type': 'supervisor',
                    })
                except CustomUser.DoesNotExist:
                    continue
            
            # Check regular staff targets
            regular_targets = PerformanceTarget.objects.filter(
                period=period
            ).filter(Q(status='pending') | Q(status='submitted')).select_related('staff', 'staff__department').values(
                'staff'
            ).annotate(
                pending_count=Count('id'),
                total_targets=Count('id', filter=Q(period=period)),
                oldest_pending=Min('created_at')
            )
            
            for item in regular_targets:
                try:
                    staff = CustomUser.objects.get(id=item['staff'])
                    
                    # Get staff profile
                    try:
                        profile = StaffProfile.objects.get(user=staff)
                        designation = profile.designation or staff.get_role_display()
                        pf_number = profile.pf_number or getattr(staff, 'pf_number', 'N/A')
                    except StaffProfile.DoesNotExist:
                        designation = staff.get_role_display()
                        pf_number = getattr(staff, 'pf_number', 'N/A')
                    
                    staff_list.append({
                        'staff': staff,
                        'staff_id': staff.id,
                        'staff_name': staff.get_full_name(),
                        'staff_role': staff.get_role_display(),
                        'staff_role_code': staff.role,
                        'department': staff.department.name if staff.department else 'N/A',
                        'department_id': staff.department.id if staff.department else None,
                        'designation': designation,
                        'pf_number': pf_number,
                        'email': staff.email,
                        'pending_count': item['pending_count'],
                        'total_targets': item['total_targets'],
                        'oldest_pending': item['oldest_pending'],
                        'days_pending': (timezone.now().date() - item['oldest_pending'].date()).days if item['oldest_pending'] else None,
                        'completion_rate': round(((item['total_targets'] - item['pending_count']) / item['total_targets'] * 100) if item['total_targets'] > 0 else 0, 1),
                        'target_type': 'regular',
                    })
                except CustomUser.DoesNotExist:
                    continue
            
            # Apply filters
            if target_filter.department:
                staff_list = [s for s in staff_list if target_filter.department.lower() in s['department'].lower()]
            
            if target_filter.staff_role:
                staff_list = [s for s in staff_list if s['staff_role_code'] == target_filter.staff_role]
            
            # Sort by pending count (highest first)
            staff_list.sort(key=lambda x: x['pending_count'], reverse=True)
            
            # Calculate totals
            total_staff = len(staff_list)
            total_pending = sum(s['pending_count'] for s in staff_list)
            total_targets = sum(s['total_targets'] for s in staff_list)
            
            # Calculate statistics
            stats = {
                'total_staff': total_staff,
                'total_pending': total_pending,
                'total_targets': total_targets,
                'supervisor_count': len([s for s in staff_list if s['target_type'] == 'supervisor']),
                'regular_count': len([s for s in staff_list if s['target_type'] == 'regular']),
                'avg_pending_per_staff': round(total_pending / total_staff, 1) if total_staff > 0 else 0,
                'max_pending': max([s['pending_count'] for s in staff_list]) if staff_list else 0,
                'min_pending': min([s['pending_count'] for s in staff_list]) if staff_list else 0,
            }
            
            return {
                "success": True,
                "staff_list": staff_list,
                "stats": stats,
                "total_staff": total_staff,
                "total_pending": total_pending,
                "active_period": period,
            }
            
        except Exception as e:
            logger.error(f"Error getting staff with pending targets: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Error retrieving staff data: {str(e)}"}